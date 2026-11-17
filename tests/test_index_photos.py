import datetime


def test_custom_labels_parsed_and_normalized(lf1):
    meta = {"customlabels": " Sam,  Sally ,sam,, Golden  Retriever "}
    assert lf1.parse_custom_labels(meta) == ["sam", "sally", "golden retriever"]


def test_custom_labels_key_case_insensitive(lf1):
    assert lf1.parse_custom_labels({"customLabels": "Beach"}) == ["beach"]
    assert lf1.parse_custom_labels({}) == []
    assert lf1.parse_custom_labels(None) == []


def test_rfc2047_encoded_metadata(lf1):
    # S3 returns non ASCII metadata like this
    assert lf1.decode_header_value("=?UTF-8?B?Q2Fmw6ksIE11bmljaA==?=") == "Café, Munich"


def test_supported_images(lf1):
    assert lf1.is_supported_image("a.JPG", None)
    assert lf1.is_supported_image("noext", "image/png")
    assert not lf1.is_supported_image("notes.txt", "text/plain")
    assert not lf1.is_supported_image("anim.gif", "image/gif")


def test_timestamp_format(lf1):
    dt = datetime.datetime(2018, 11, 5, 12, 40, 2, tzinfo=datetime.timezone.utc)
    assert lf1.to_timestamp(dt) == "2018-11-05T12:40:02"


def test_doc_id_stable(lf1):
    assert lf1.doc_id("b", "my photo.jpg") == lf1.doc_id("b", "my photo.jpg")
    assert lf1.doc_id("b", "x.jpg") != lf1.doc_id("b", "y.jpg")


def test_handler_indexes_with_custom_and_detected_labels(lf1, monkeypatch):
    calls = []
    monkeypatch.setattr(lf1, "_index_ready", True)
    monkeypatch.setattr(lf1.s3, "head_object", lambda **kw: {
        "ContentLength": 10, "ContentType": "image/jpeg",
        "LastModified": datetime.datetime(2026, 11, 15, 10, 0, 0, tzinfo=datetime.timezone.utc),
        "Metadata": {"customlabels": "Sam, Sally"}})
    monkeypatch.setattr(lf1.rekognition, "detect_labels", lambda **kw: {"Labels": [
        {"Name": "Dog", "Parents": [{"Name": "Animal"}, {"Name": "Pet"}]},
        {"Name": "Person", "Aliases": [{"Name": "Human"}]}]})
    monkeypatch.setattr(lf1, "os_request", lambda m, p, b=None: calls.append((m, p, b)) or (201, {}))
    event = {"Records": [{"eventSource": "aws:s3", "eventName": "ObjectCreated:Put",
                          "s3": {"bucket": {"name": "b2"}, "object": {"key": "my+dog.jpg"}}}]}
    lf1.lambda_handler(event, None)
    method, path, body = calls[0]
    assert method == "PUT" and path.startswith("/photos/_doc/")
    assert body["objectKey"] == "my dog.jpg"          # URL decoded key
    assert body["bucket"] == "b2"
    assert body["createdTimestamp"] == "2026-11-15T10:00:00"
    assert body["labels"] == ["sam", "sally", "dog", "animal", "pet", "person", "human"]


def test_handler_skips_non_images(lf1, monkeypatch):
    monkeypatch.setattr(lf1, "_index_ready", True)
    monkeypatch.setattr(lf1.s3, "head_object", lambda **kw: {
        "ContentLength": 10, "ContentType": "text/plain", "Metadata": {}})
    event = {"Records": [{"eventSource": "aws:s3", "eventName": "ObjectCreated:Put",
                          "s3": {"bucket": {"name": "b2"}, "object": {"key": "notes.txt"}}}]}
    out = lf1.lambda_handler(event, None)
    assert "not a JPEG/PNG image" in out["body"]
