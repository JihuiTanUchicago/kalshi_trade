"""llm.extract_json: parsing the model's JSON replies."""
import pytest

from app.llm import extract_json


def test_a_broken_batch_keeps_its_complete_items():
    """Prod run 2830 lost a whole proposing round to one stray character at char 13047."""
    good = '{"title": "A", "thesis": "x", "spec": {"side": "yes"}}'
    broken = '{"hypotheses": [%s, %s, {"title": "C", "thesis": "it "breaks" here"}]}' % (good, good)
    assert [h["title"] for h in extract_json(broken)["hypotheses"]] == ["A", "A"]
    clipped = '{"hypotheses": [%s, {"title": "B", "thes' % good
    assert len(extract_json(clipped + "}")["hypotheses"]) == 1
    with pytest.raises(ValueError):
        extract_json('{"decision": "refine", "spec": {"side": "yes",, }}')  # not a list reply
