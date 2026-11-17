"""Inspect or reset the OpenSearch "photos" index from your laptop.

Uses your local AWS credentials (aws configure). Your IAM user/role must be allowed
in the domain access policy for this to work.

  python scripts/os_query.py --endpoint search-photos-xxxx.us-east-1.es.amazonaws.com list
  python scripts/os_query.py --endpoint ... search dog
  python scripts/os_query.py --endpoint ... reset      # deletes the index (LF1 recreates it)
"""
import argparse
import json
import urllib.error
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def call(host, region, method, path, body=None):
    url = f"https://{host}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = AWSRequest(method=method, url=url, data=data, headers={"Content-Type": "application/json"})
    SigV4Auth(boto3.Session().get_credentials().get_frozen_credentials(), "es", region).add_auth(req)
    r = urllib.request.Request(url, data=data, method=method, headers=dict(req.headers.items()))
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        return {"status": err.code, "error": err.read().decode()}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint", required=True)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--index", default="photos")
    p.add_argument("action", choices=["list", "search", "mapping", "reset"])
    p.add_argument("term", nargs="?")
    a = p.parse_args()
    host = a.endpoint.replace("https://", "").rstrip("/")
    if a.action == "list":
        out = call(host, a.region, "POST", f"/{a.index}/_search", {"size": 100, "query": {"match_all": {}}})
    elif a.action == "search":
        out = call(host, a.region, "POST", f"/{a.index}/_search", {"query": {"match": {"labels": a.term}}})
    elif a.action == "mapping":
        out = call(host, a.region, "GET", f"/{a.index}/_mapping")
    else:
        out = call(host, a.region, "DELETE", f"/{a.index}")
    print(json.dumps(out, indent=2))
