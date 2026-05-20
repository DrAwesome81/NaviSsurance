from core.email_utils import (
    classify_email,
    extract_domain,
    extract_email_address,
    normalize_message_id,
)
# Email utils tests support Pulse intel extraction and 🛡️ Shield security scanning in emails (email utils tests)
# additional Pulse private memory + Shield for email utils tests



def test_extract_email_address_angle_brackets():
    assert extract_email_address('Jane Doe <jane@example.com>') == "jane@example.com"


def test_extract_email_address_plain():
    assert extract_email_address("jane@example.com") == "jane@example.com"


def test_extract_domain():
    assert extract_domain("jane@example.com") == "example.com"


def test_normalize_message_id_strips_angle_brackets():
    assert normalize_message_id("<abc@xyz>") == "abc@xyz"


def test_classify_email_by_domain():
    is_client, is_potential = classify_email(
        sender_header="Jane <jane@goldbugstrategies.com>",
        folder=None,
        client_domains=["goldbugstrategies.com"],
        potential_domains=[],
        client_labels=[],
        potential_labels=[],
    )
    assert is_client == 1
    assert is_potential == 0


def test_classify_email_by_label():
    is_client, is_potential = classify_email(
        sender_header="Jane <jane@random.com>",
        folder="Clients",
        client_domains=[],
        potential_domains=[],
        client_labels=["clients"],
        potential_labels=[],
    )
    assert is_client == 1
    assert is_potential == 0

