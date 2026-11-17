"""LF1: index-photos

Triggered by S3 ObjectCreated (PUT) events on the photos bucket (B2).
For every new photo it:
  1. reads the object's metadata with headObject and parses x-amz-meta-customLabels (A1)
  2. calls Rekognition DetectLabels on the object
  3. stores {objectKey, bucket, createdTimestamp, labels} in the OpenSearch/ElasticSearch "photos" index

It also handles ObjectRemoved events (optional trigger) by deleting the photo from the index,
so deleted photos never show up as broken results.

No third party dependencies: OpenSearch is called over HTTPS with requests signed by
botocore's SigV4 signer, so the deployment zip is just this file.
"""

import datetime
import email.header
import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import unquote_plus

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "us-east-1")
OS_HOST = re.sub(r"^https?://", "", os.environ.get("OPENSEARCH_ENDPOINT", "")).rstrip("/")
INDEX = os.environ.get("OPENSEARCH_INDEX", "photos")
MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "70"))
MAX_LABELS = int(os.environ.get("MAX_LABELS", "50"))
INCLUDE_PARENT_LABELS = os.environ.get("INCLUDE_PARENT_LABELS", "true").lower() == "true"

# Rekognition DetectLabels only accepts JPEG and PNG
SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png")
SUPPORTED_CONTENT_TYPES = ("image/jpeg", "image/jpg", "image/png")
MAX_LABEL_LENGTH = 100

_boto_cfg = Config(retries={"max_attempts": 5, "mode": "standard"})
_session = boto3.Session()
s3 = boto3.client("s3", config=_boto_cfg)
rekognition = boto3.client("rekognition", config=_boto_cfg)

INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "objectKey": {"type": "keyword"},
            "bucket": {"type": "keyword"},
            "createdTimestamp": {
                "type": "date",
                "format": "strict_date_hour_minute_second||strict_date_optional_time",
            },
            # english analyzer = stemming, so "dogs" matches "dog"; raw = exact match
            "labels": {
                "type": "text",
                "analyzer": "english",
                "fields": {"raw": {"type": "keyword"}},
            },
        }
    },
}

_index_ready = False  # cached per warm container


# ---------------------------------------------------------------- OpenSearch helpers
def os_request(method, path, body=None, retries=3):
    """Signed HTTPS request to the OpenSearch domain. Returns (status, parsed_json)."""
    if not OS_HOST:
        raise RuntimeError("OPENSEARCH_ENDPOINT environment variable is not set")
    url = f"https://{OS_HOST}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(1, retries + 1):
        aws_req = AWSRequest(method=method, url=url, data=data,
                             headers={"Content-Type": "application/json"})
        creds = _session.get_credentials().get_frozen_credentials()
        SigV4Auth(creds, "es", REGION).add_auth(aws_req)
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=dict(aws_req.headers.items()))
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                payload = json.loads(raw) if raw else {}
            except ValueError:
                payload = {"raw": raw.decode("utf-8", "replace")}
            # retry throttling and transient server errors only
            if err.code in (429, 502, 503, 504) and attempt < retries:
                time.sleep(0.5 * 2 ** attempt)
                continue
            return err.code, payload
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(0.5 * 2 ** attempt)
                continue
            raise


def ensure_index():
    """Create the photos index with our mapping if it does not exist yet."""
    global _index_ready
    if _index_ready:
        return
    status, _ = os_request("HEAD", f"/{INDEX}")
    if status == 404:
        status, payload = os_request("PUT", f"/{INDEX}", INDEX_BODY)
        err_type = (payload.get("error") or {}).get("type") if isinstance(payload.get("error"), dict) else None
        # a concurrent invocation may have created it first; that is fine
        if status >= 300 and err_type != "resource_already_exists_exception":
            raise RuntimeError(f"Could not create index {INDEX}: {status} {payload}")
        logger.info("Index %s created", INDEX)
    elif status >= 300:
        raise RuntimeError(f"Could not check index {INDEX}: HTTP {status}")
    _index_ready = True


def doc_id(bucket, key):
    # hashing avoids URL encoding/signature issues with spaces or unicode in keys
    return hashlib.sha1(f"{bucket}/{key}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- label helpers
def decode_header_value(value):
    """S3 returns non ASCII metadata RFC 2047 encoded (=?UTF-8?B?...?=). Decode it."""
    if not value or "=?" not in value:
        return value or ""
    parts = []
    for chunk, charset in email.header.decode_header(value):
        parts.append(chunk.decode(charset or "utf-8", "replace") if isinstance(chunk, bytes) else chunk)
    return "".join(parts)


def normalize_label(label):
    label = re.sub(r"\s+", " ", str(label)).strip().strip("\"'").strip().lower()
    return label[:MAX_LABEL_LENGTH]


def parse_custom_labels(metadata):
    """Find x-amz-meta-customLabels (S3 lowercases it to 'customlabels') and build A1."""
    raw = ""
    for k, v in (metadata or {}).items():
        if k.lower().replace("-", "").replace("_", "") == "customlabels":
            raw = v
            break
    raw = decode_header_value(raw)
    return dedupe(normalize_label(part) for part in raw.split(","))


def dedupe(items):
    seen, out = set(), []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def rekognition_labels(bucket, key):
    try:
        resp = rekognition.detect_labels(
            Image={"S3Object": {"Bucket": bucket, "Name": key}},
            MaxLabels=MAX_LABELS,
            MinConfidence=MIN_CONFIDENCE,
        )
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "")
        if code in ("InvalidImageFormatException", "ImageTooLargeException",
                    "InvalidS3ObjectException", "InvalidParameterException"):
            logger.warning("Rekognition could not process s3://%s/%s: %s", bucket, key, code)
            return []
        raise  # throttling etc: let the invocation fail so S3 retries it
    labels = []
    for item in resp.get("Labels", []):
        labels.append(item.get("Name"))
        for alias in item.get("Aliases", []) or []:
            labels.append(alias.get("Name"))
        if INCLUDE_PARENT_LABELS:
            for parent in item.get("Parents", []) or []:
                labels.append(parent.get("Name"))
    return dedupe(normalize_label(l) for l in labels if l)


# ---------------------------------------------------------------- record processing
def is_supported_image(key, content_type):
    ct = (content_type or "").split(";")[0].strip().lower()
    return key.lower().endswith(SUPPORTED_EXTENSIONS) or ct in SUPPORTED_CONTENT_TYPES


def to_timestamp(dt):
    if not isinstance(dt, datetime.datetime):
        dt = datetime.datetime.now(datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def index_object(bucket, key):
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            logger.warning("s3://%s/%s no longer exists, skipping", bucket, key)
            return {"key": key, "status": "skipped", "reason": "object not found"}
        raise

    if head.get("ContentLength", 0) == 0:
        return {"key": key, "status": "skipped", "reason": "empty object"}
    if not is_supported_image(key, head.get("ContentType")):
        logger.warning("Skipping unsupported file s3://%s/%s (%s)", bucket, key, head.get("ContentType"))
        return {"key": key, "status": "skipped", "reason": "not a JPEG/PNG image"}

    custom = parse_custom_labels(head.get("Metadata"))       # A1
    detected = rekognition_labels(bucket, key)
    labels = dedupe(custom + detected)                       # append Rekognition labels to A1
    if not labels:
        logger.warning("No labels for s3://%s/%s, indexing anyway", bucket, key)

    document = {
        "objectKey": key,
        "bucket": bucket,
        "createdTimestamp": to_timestamp(head.get("LastModified")),
        "labels": labels,
    }
    status, payload = os_request("PUT", f"/{INDEX}/_doc/{doc_id(bucket, key)}?refresh=wait_for", document)
    if status >= 300:
        raise RuntimeError(f"Indexing failed for {key}: {status} {payload}")
    logger.info("Indexed %s", json.dumps(document))
    return {"key": key, "status": "indexed", "document": document}


def delete_object(bucket, key):
    status, payload = os_request("DELETE", f"/{INDEX}/_doc/{doc_id(bucket, key)}?refresh=wait_for")
    if status not in (200, 404):
        raise RuntimeError(f"Delete failed for {key}: {status} {payload}")
    return {"key": key, "status": "deleted" if status == 200 else "not indexed"}


def lambda_handler(event, context):
    logger.info("Event: %s", json.dumps(event))
    records = (event or {}).get("Records") or []
    if not records:
        return {"statusCode": 400, "body": "No S3 records in event"}

    ensure_index()
    results, failures = [], 0
    for record in records:
        if record.get("eventSource") != "aws:s3":
            continue
        name = record.get("eventName", "")
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])   # keys arrive URL encoded
        if key.endswith("/"):
            continue  # "folder" placeholder objects
        try:
            if name.startswith("ObjectRemoved"):
                results.append(delete_object(bucket, key))
            else:
                results.append(index_object(bucket, key))
        except Exception as exc:  # keep going for the other records
            logger.exception("Failed processing s3://%s/%s", bucket, key)
            failures += 1
            results.append({"key": key, "status": "error", "error": str(exc)})

    if failures:
        # raising makes S3's async invocation retry (twice) for transient errors
        raise RuntimeError(f"{failures} record(s) failed: {json.dumps(results)}")
    return {"statusCode": 200, "body": json.dumps(results)}
