# AI Photo Search: frontend (CC Fall 2026 Assignment 3)

Static site hosted on S3 (B1). Search with GET /search, upload with PUT /photos/{object},
custom labels sent as the x-amz-meta-customLabels header. Uses the API Gateway generated JavaScript SDK.

1. Unzip the generated SDK into sdk/ (apigClient.js + lib/)
2. Put your API key in config.js
3. Push to GitHub: pipeline P2 deploys this repo to the frontend bucket
