# AI Photo Search: backend (CC Fall 2026 Assignment 3)

| Path | What it is |
|---|---|
| lambdas/index-photos | LF1: S3 PUT trigger, Rekognition labels + x-amz-meta-customLabels, indexes into OpenSearch "photos" |
| lambdas/search-photos | LF2: GET /search, Lex V2 disambiguation, OpenSearch query, presigned photo URLs |
| tests/ | pytest unit tests (run in pipeline P1 before deploying) |
| buildspec.yml | CodeBuild spec for pipeline P1 (test, zip, update both Lambdas) |
| cloudformation/template.yaml | T1: Lambdas, API Gateway, B1, B2, IAM (optional OpenSearch domain) |
| lex/README.md | Lex bot definition: SearchIntent, slots, utterances |
| scripts/os_query.py | Inspect or reset the OpenSearch index from your laptop |

Lambda environment variables: OPENSEARCH_ENDPOINT (both), LEX_BOT_ID and LEX_BOT_ALIAS_ID (LF2).
No third party packages: both Lambdas sign OpenSearch requests with botocore SigV4.

Run tests: `pip install boto3 pytest && python -m pytest -q`
