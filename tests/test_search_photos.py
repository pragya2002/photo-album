import json


def test_clean_keyword_splits_and_strips(lf2):
    assert lf2.clean_keyword("cats and dogs") == ["cats", "dogs"]
    assert lf2.clean_keyword("photos of trees, birds") == ["trees", "birds"]
    assert lf2.clean_keyword("the Christmas tree") == ["christmas tree"]
    assert lf2.clean_keyword("show me") == []


def test_singular(lf2):
    assert lf2.singular("dogs") == "dog"
    assert lf2.singular("puppies") == "puppy"
    assert lf2.singular("beaches") == "beach"
    assert lf2.singular("people") == "person"
    assert lf2.singular("glass") == "glass"
    assert lf2.singular("bus") == "bus"


def test_build_query_or_semantics(lf2):
    q = lf2.build_query(["cats", "dogs"])
    should = q["query"]["bool"]["should"]
    assert q["query"]["bool"]["minimum_should_match"] == 1
    assert set(should[0]["terms"]["labels.raw"]) == {"cats", "cat", "dogs", "dog"}


def _lex_reply(intent, slots):
    return {"sessionState": {"intent": {"name": intent, "slots": slots}}}


def test_disambiguate_two_slots(lf2, monkeypatch):
    slots = {"keywordOne": {"value": {"originalValue": "cats", "interpretedValue": "cat"}},
             "keywordTwo": {"value": {"originalValue": "dogs", "interpretedValue": "dogs"}}}
    monkeypatch.setattr(lf2.lex, "recognize_text", lambda **kw: _lex_reply("SearchIntent", slots))
    assert lf2.disambiguate("show me cats and dogs") == ["cats", "cat", "dogs"]


def test_disambiguate_fallback_intent_gives_no_keywords(lf2, monkeypatch):
    monkeypatch.setattr(lf2.lex, "recognize_text", lambda **kw: _lex_reply("FallbackIntent", {}))
    assert lf2.disambiguate("asdfgh") == []


def test_empty_query_returns_empty_results(lf2):
    out = lf2.lambda_handler({"queryStringParameters": None}, None)
    assert out["statusCode"] == 200 and json.loads(out["body"]) == {"results": []}
    assert out["headers"]["Access-Control-Allow-Origin"] == "*"


def test_no_keywords_returns_empty(lf2, monkeypatch):
    monkeypatch.setattr(lf2, "disambiguate", lambda q: [])
    out = lf2.lambda_handler({"queryStringParameters": {"q": "hello"}}, None)
    assert json.loads(out["body"]) == {"results": []}


def test_results_shape_and_dedupe(lf2, monkeypatch):
    monkeypatch.setattr(lf2, "disambiguate", lambda q: ["dog"])
    hit = {"_source": {"bucket": "b2", "objectKey": "a.jpg", "labels": ["dog"]}}
    monkeypatch.setattr(lf2, "search_index", lambda k: [hit, hit])
    out = lf2.lambda_handler({"queryStringParameters": {"q": "dogs"}}, None)
    body = json.loads(out["body"])
    assert len(body["results"]) == 1
    assert body["results"][0]["labels"] == ["dog"]
    assert "a.jpg" in body["results"][0]["url"]


def test_lex_failure_returns_error_schema(lf2, monkeypatch):
    def boom(q):
        raise RuntimeError("lex down")
    monkeypatch.setattr(lf2, "disambiguate", boom)
    out = lf2.lambda_handler({"queryStringParameters": {"q": "dogs"}}, None)
    assert out["statusCode"] == 500
    assert json.loads(out["body"])["code"] == 500


def test_missing_index_returns_empty(lf2, monkeypatch):
    monkeypatch.setattr(lf2, "os_request", lambda *a, **k: (404, {}))
    assert lf2.search_index(["dog"]) == []
