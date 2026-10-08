import pytest

from agent_memory.domain.content_policy import sensitive


@pytest.mark.parametrize("identifier", [
    "12345678-1234-4234-8123-123456789012",
    "abcdefab-1234-4234-8123-13812345678a",
    "ABCDEFAB-1234-4234-8123-13812345678A",
])
def test_uuid_identifiers_do_not_look_like_phone_or_card(identifier):
    assert not sensitive('{"run_id":"' + identifier + '","request":"水壶"}')


@pytest.mark.parametrize("content", [
    "api_key=12345678-1234-4234-8123-123456789012",
    "ark-12345678-1234-4234-8123-123456789012",
    "12345678-1234-4234-8123-123456789012 卡号 4111 1111 1111 1111",
    "12345678-1234-4234-8123-123456789012 手机 13812345678",
    "身份证 11010519491231002X",
    "12345678-1234-4234-8123-12345678901",  # malformed UUID is not exempt
    "x12345678-1234-4234-8123-123456789012",  # token prefix is not exempt
])
def test_uuid_exemption_does_not_disable_sensitive_detection(content):
    assert sensitive(content)
