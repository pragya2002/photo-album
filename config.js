// Fill these in after you create the API key (API Gateway > API keys > Show key).
// Note: any key shipped in a static site is visible to visitors; the usage plan limits abuse.
window.APP_CONFIG = {
  apiKey: "go8BczmH245tMWJplZ83w2BAePnVgGvT9Eh1Ai1Q",
  maxUploadBytes: 10 * 1024 * 1024, // API Gateway payload limit is 10 MB
  allowedTypes: ["image/jpeg", "image/png"], // Rekognition supports JPEG and PNG
  maxLabels: 20,
  maxLabelLength: 50,
};
