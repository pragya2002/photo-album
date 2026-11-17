# AI Photo Search (CC Fall 2026, Assignment 3)

Team: Pragya Awasthi (pa2755), Aditya Jha (aj4955)

Natural language photo search on AWS: upload photos with optional custom labels, then search them in plain English ("show me dogs and trees").

| Folder | Contents |
|---|---|
| `front-end/` | Static website hosted on S3 (B1): search, upload with custom labels, API Gateway generated JavaScript SDK |
| `lambda-functions/` | LF1 `index-photos` (S3 trigger, Rekognition + custom labels into OpenSearch), LF2 `search-photos` (Lex V2 + OpenSearch search), unit tests |
| `other-scripts/` | CloudFormation template T1, CodeBuild buildspecs for pipelines P1 and P2, Lex bot definition, OpenSearch debug script |

## Architecture
- **Upload:** frontend → API Gateway `PUT /photos/{object}` (S3 proxy, `x-amz-meta-customLabels` header) → S3 photos bucket (B2) → LF1 → Rekognition DetectLabels + custom labels → OpenSearch index `photos`
- **Search:** frontend → API Gateway `GET /search?q=` (API key) → LF2 → Lex V2 `SearchIntent` extracts keywords → OpenSearch query → presigned photo URLs

## CI/CD
- **P1** (CodePipeline + CodeBuild, `other-scripts/buildspec.yml`): a push touching `lambda-functions/` runs the unit tests and updates both Lambda functions.
- **P2** (CodePipeline + CodeBuild, `other-scripts/buildspec-frontend.yml`): a push touching `front-end/` packages the site and deploys it to the S3 website bucket.

## CloudFormation
`other-scripts/cloudformation/template.yaml` (T1) creates both Lambdas, the API Gateway API (with API key, usage plan and CORS), both S3 buckets (public website URL in the stack outputs) and all IAM roles.
