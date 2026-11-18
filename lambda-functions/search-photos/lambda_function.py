"""LF2: search-photos

GET /search?q={query text}  (API Gateway Lambda proxy integration)

1. Sends q to the Amazon Lex V2 bot (SearchIntent) to disambiguate it into keywords K1..Kn
2. If Lex yields keywords, searches the "photos" OpenSearch/ElasticSearch index
3. Returns {"results": [{"url": ..., "labels": [...]}, ...]} as per the Swagger spec,
   or {"results": []} when Lex finds no keywords.

Errors follow the spec's Error schema: {"code": 500, "message": "..."}.
"""

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import uuid

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "us-east-1")
OS_HOST = re.sub(r"^https?://", "", os.environ.get("OPENSEARCH_ENDPOINT", "")).rstrip("/")
INDEX = os.environ.get("OPENSEARCH_INDEX", "photos")
LEX_BOT_ID = os.environ.get("LEX_BOT_ID", "")
LEX_BOT_ALIAS_ID = os.environ.get("LEX_BOT_ALIAS_ID", "TSTALIASID")
LEX_LOCALE_ID = os.environ.get("LEX_LOCALE_ID", "en_US")
SEARCH_INTENT = os.environ.get("SEARCH_INTENT", "SearchIntent")
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "100"))
URL_EXPIRY = int(os.environ.get("URL_EXPIRY_SECONDS", "3600"))
MAX_QUERY_LENGTH = 1000  # Lex RecognizeText accepts up to 1024 characters

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Api-Key,x-amz-meta-customLabels",
    "Access-Control-Allow-Methods": "GET,PUT,OPTIONS",
    "Content-Type": "application/json",
}

# words that are never search keywords, even if Lex leaves them inside a slot value
STOPWORDS = {
    "a", "an", "the", "me", "show", "find", "search", "for", "of", "with", "in", "on",
    "them", "it", "photo", "photos", "picture", "pictures", "pic", "pics", "image",
    "images", "some", "any", "all", "please", "and", "or", "that", "have", "has",
    "containing", "contain", "contains", "featuring", "i", "want", "to", "see", "my",
}
IRREGULAR = {
    "people": "person", "men": "man", "women": "woman", "children": "child",
    "kids": "child", "mice": "mouse", "geese": "goose", "feet": "foot",
    "teeth": "tooth", "leaves": "leaf", "knives": "knife", "wolves": "wolf",
    "puppies": "puppy", "dogs": "dog", "cats": "cat",
}

_boto_cfg = Config(retries={"max_attempts": 3, "mode": "standard"})
_session = boto3.Session()
lex = boto3.client("lexv2-runtime", config=_boto_cfg)
s3 = boto3.client("s3", region_name=REGION,
                  config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}))


# ---------------------------------------------------------------- helpers
def respond(status, body):
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps(body)}


def error(status, message):
    return respond(status, {"code": status, "message": message})


def singular(word):
    if word in IRREGULAR:
        return IRREGULAR[word]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and re.search(r"(ches|shes|sses|xes|zes)$", word):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def clean_keyword(value):
    """Split a raw slot value into keywords: 'cats and dogs' -> ['cats', 'dogs']."""
    out = []
    for piece in re.split(r",|;|&|\band\b|\bor\b|\+", (value or "").lower()):
        tokens = [t for t in re.findall(r"[a-z0-9'\-]+", piece) if t not in STOPWORDS]
        phrase = " ".join(tokens).strip("'-")
        if phrase:
            out.append(phrase)
    return out


def dedupe(items):
    seen, out = set(), []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ---------------------------------------------------------------- Lex
def slot_values(slot):
    """Return original and interpreted values from a Lex V2 slot (single or multi valued)."""
    values = []
    if not slot:
        return values
    containers = [slot.get("value")] + [v.get("value") for v in slot.get("values") or []]
    for c in containers:
        if not c:
            continue
        values.append(c.get("originalValue"))
        values.append(c.get("interpretedValue"))
        values.extend(c.get("resolvedValues") or [])
    return [v for v in values if v]


def disambiguate(query):
    """Ask Lex for the keywords in the query. Returns [] if Lex finds none."""
    if not LEX_BOT_ID:
        raise RuntimeError("LEX_BOT_ID environment variable is not set")
    resp = lex.recognize_text(
        botId=LEX_BOT_ID,
        botAliasId=LEX_BOT_ALIAS_ID,
        localeId=LEX_LOCALE_ID,
        sessionId=uuid.uuid4().hex,  # fresh session: no slot values leak between searches
        text=query,
    )
    intent = (resp.get("sessionState") or {}).get("intent") or {}
    logger.info("Lex intent=%s slots=%s", intent.get("name"), json.dumps(intent.get("slots")))
    if intent.get("name") != SEARCH_INTENT:
        return []
    keywords = []
    for slot in (intent.get("slots") or {}).values():
        for value in slot_values(slot):
            keywords.extend(clean_keyword(value))
    return dedupe(keywords)


# ---------------------------------------------------------------- OpenSearch
def os_request(method, path, body=None, retries=3):
    if not OS_HOST:
        raise RuntimeError("OPENSEARCH_ENDPOINT environment variable is not set")
    url = f"https://{OS_HOST}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(1, retries + 1):
        aws_req = AWSRequest(method=method, url=url, data=data,
                             headers={"Content-Type": "application/json"})
        SigV4Auth(_session.get_credentials().get_frozen_credentials(), "es", REGION).add_auth(aws_req)
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=dict(aws_req.headers.items()))
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                payload = json.loads(raw) if raw else {}
            except ValueError:
                payload = {"raw": raw.decode("utf-8", "replace")}
            if err.code in (429, 502, 503, 504) and attempt < retries:
                time.sleep(0.3 * 2 ** attempt)
                continue
            return err.code, payload
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(0.3 * 2 ** attempt)
                continue
            raise


def build_query(keywords):
    """OR across keywords: a photo matches if it has ANY of the keywords.
    Photos matching more keywords score higher and come first."""
    variants = dedupe(v for k in keywords for v in (k, singular(k)))
    should = [{"terms": {"labels.raw": variants}}]
    for v in variants:
        should.append({"match": {"labels": {"query": v, "operator": "and"}}})
    return {
        "size": MAX_RESULTS,
        "_source": ["objectKey", "bucket", "labels"],
        "query": {"bool": {"should": should, "minimum_should_match": 1}},
    }


def search_index(keywords):
    status, payload = os_request("POST", f"/{INDEX}/_search", build_query(keywords))
    if status == 404:
        logger.warning("Index %s does not exist yet", INDEX)
        return []
    if status >= 300:
        raise RuntimeError(f"OpenSearch error {status}: {payload}")
    return payload.get("hits", {}).get("hits", [])


def to_results(hits):
    results, seen = [], set()
    for hit in hits:
        src = hit.get("_source") or {}
        bucket, key = src.get("bucket"), src.get("objectKey")
        if not bucket or not key or (bucket, key) in seen:
            continue
        seen.add((bucket, key))
        url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key},
                                        ExpiresIn=URL_EXPIRY)
        results.append({"url": url, "labels": src.get("labels") or []})
    return results


# ---------------------------------------------------------------- handler
def lambda_handler(event, context):
    event = event or {}
    if event.get("httpMethod") == "OPTIONS":
        return respond(200, {})

    params = event.get("queryStringParameters") or {}
    query = params.get("q") if "queryStringParameters" in event else event.get("q")
    query = re.sub(r"\s+", " ", (query or "")).strip()[:MAX_QUERY_LENGTH]
    logger.info("Search query: %r", query)
    if not query:
        return respond(200, {"results": []})

    try:
        keywords = disambiguate(query)
    except (ClientError, BotoCoreError, RuntimeError) as exc:
        logger.exception("Lex disambiguation failed")
        return error(500, f"Could not interpret the query: {exc}")
    logger.info("Keywords: %s", keywords)
    if not keywords:
        return respond(200, {"results": []})

    try:
        results = to_results(search_index(keywords))
    except Exception as exc:
        logger.exception("Search failed")
        return error(500, f"Search failed: {exc}")
    logger.info("Returning %d result(s) for keywords %s", len(results), keywords)
    return respond(200, {"results": results})
