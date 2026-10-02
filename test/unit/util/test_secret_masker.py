import base64
import io

from galaxy.util.secret_masker import (
    mask_secrets,
    read_masked_chunk,
    secret_forms,
    shrink_masked,
)


def test_every_copy_is_masked():
    forms = secret_forms(["s3cret-1"])
    assert mask_secrets("a s3cret-1 b s3cret-1", forms) == "a *** b ***"
    assert mask_secrets("nothing to hide", forms) == "nothing to hide"
    assert mask_secrets(None, forms) is None


def test_overlapping_values_are_masked_together():
    # Replacing one value at a time would leave "ijkl" of the second one showing.
    forms = secret_forms(["abcdefgh", "efghijkl"])
    assert mask_secrets("xx abcdefghijkl yy", forms) == "xx *** yy"


def test_short_and_placeholder_values_are_not_masked():
    assert secret_forms(["abc", "true", "None", "", "  "]) == []
    assert secret_forms([" abcd "]) == ["abcd"]


def test_a_multi_line_value_is_masked_line_by_line():
    forms = secret_forms(["first-line-secret\nsecond-line-secret"])
    assert mask_secrets("second-line-secret\r\nfirst-line-secret", forms) == "***\r\n***"


def test_url_encoded_and_json_escaped_copies_are_masked():
    url_forms = secret_forms(["p@ss:word/1"])
    assert mask_secrets("https://example.org/?key=p%40ss%3Aword%2F1", url_forms) == "https://example.org/?key=***"
    json_forms = secret_forms(['pa"ss-word'])
    assert mask_secrets('{"key": "pa\\"ss-word"}', json_forms) == '{"key": "***"}'


def test_a_value_inside_base64_is_masked_at_any_position():
    forms = secret_forms(["hunter2-secret"])
    # User names of 3, 4 and 5 characters put the password at each base64 alignment.
    for user in ("bob", "carl", "alice"):
        header = base64.b64encode(f"{user}:hunter2-secret".encode()).decode()
        masked = mask_secrets(f"Authorization: Basic {header}", forms)
        assert masked is not None
        shown = masked.removeprefix("Authorization: Basic ")
        assert "***" in shown
        # Only the part that encodes the user name, one edge character and the padding stay readable.
        shown_length = len(shown.replace("***", "").rstrip("="))
        assert shown_length <= len(base64.b64encode(f"{user}:".encode()).rstrip(b"=")) + 1


def test_keep_length_hides_each_character():
    assert mask_secrets("x s3cret-1 y", secret_forms(["s3cret-1"]), keep_length=True) == "x ******** y"


def test_reading_in_chunks_masks_a_value_cut_by_a_chunk(tmp_path):
    path = tmp_path / "tool_stdout"
    path.write_text("aaaa s3cret-value bbbb\n")
    forms = secret_forms(["s3cret-value"])
    received = ""
    for _ in range(10):
        received += read_masked_chunk(str(path), len(received), 7, forms)
    assert received == "aaaa ************ bbbb\n"


def test_a_value_still_being_written_is_held_back(tmp_path):
    path = tmp_path / "tool_stdout"
    path.write_text("token: s3cret-va")
    forms = secret_forms(["s3cret-value"])
    received = read_masked_chunk(str(path), 0, 100, forms)
    assert received == "token: "
    with open(path, "a") as file:
        file.write("lue\n")
    received += read_masked_chunk(str(path), len(received), 100, forms)
    assert received == "token: ************\n"


def test_reading_without_secrets_returns_the_chunk(tmp_path):
    path = tmp_path / "tool_stdout"
    path.write_text("plain output\n")
    assert read_masked_chunk(str(path), 6, 6, []) == "output"


def test_shrinking_leaves_no_piece_of_a_secret_at_the_cuts():
    stream = io.BytesIO(b"a" * 10 + b"s3cret-value" + b"b" * 30 + b"s3cret-value" + b"c" * 10)
    # Keeping 40 of the 74 bytes cuts through both copies of the secret.
    assert shrink_masked(stream, 40, secret_forms(["s3cret-value"]), "\n..\n") == "aaaaaaaaaa\n..\ncccccccccc"
