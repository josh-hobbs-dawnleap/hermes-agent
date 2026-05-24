from argparse import ArgumentParser, Namespace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from gateway.social_errands import SocialErrandStore
from hermes_cli.errands_cmd import cmd_errands, register_errands_subparser
from hermes_cli.identity_cmd import cmd_identity, register_identity_subparser


def test_identity_parser_registers_list_and_add_commands():
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_identity_subparser(subparsers)

    listed = parser.parse_args(["identity", "list", "--person", "Julia Hobbs"])
    assert listed.func is cmd_identity
    assert listed.identity_command == "list"
    assert listed.person == "Julia Hobbs"

    added = parser.parse_args([
        "identity",
        "add",
        "telegram",
        "123",
        "Julia Hobbs",
        "--visible-name",
        "Julia",
    ])
    assert added.func is cmd_identity
    assert added.identity_command == "add"
    assert added.platform == "telegram"
    assert added.user_id == "123"
    assert added.person == "Julia Hobbs"
    assert added.visible_name == "Julia"


def test_errands_parser_registers_list_and_cancel_commands():
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_errands_subparser(subparsers)

    listed = parser.parse_args(["errands", "list", "--status", "pending"])
    assert listed.func is cmd_errands
    assert listed.errands_command == "list"
    assert listed.status == "pending"

    cancelled = parser.parse_args(["errands", "cancel", "abc123", "--actor", "Josh Hobbs"])
    assert cancelled.func is cmd_errands
    assert cancelled.errands_command == "cancel"
    assert cancelled.errand_id == "abc123"
    assert cancelled.actor == "Josh Hobbs"


def test_identity_add_and_list(tmp_path, capsys):
    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        add_rc = cmd_identity(
            Namespace(
                identity_command="add",
                platform="telegram",
                user_id="123",
                person="Julia Hobbs",
                visible_name="Julia",
                username="julia",
                confidence="explicit",
                approved_by="Josh Hobbs",
            )
        )
        list_rc = cmd_identity(Namespace(identity_command="list", person=None))

    out = capsys.readouterr().out
    assert add_rc == 0
    assert list_rc == 0
    assert "Julia Hobbs" in out
    assert "telegram:123" in out


def test_errands_list_and_cancel(tmp_path, capsys):
    path = tmp_path / "social_errands.json"
    store = SocialErrandStore(path)
    errand = store.create_pending_cue(
        created_by_person="Julia Hobbs",
        created_by_platform="telegram",
        source="telegram:123",
        target_chat="telegram:-100",
        trigger_phrase="Winston, did you have something to tell Josh?",
        message="Happy birthday, Josh!",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        list_rc = cmd_errands(Namespace(errands_command="list", status=None))
        cancel_rc = cmd_errands(Namespace(errands_command="cancel", errand_id=errand.errand_id, actor="Josh Hobbs"))

    out = capsys.readouterr().out
    assert list_rc == 0
    assert cancel_rc == 0
    assert errand.errand_id in out
    assert "Happy birthday" in out
    assert SocialErrandStore(path).get_errand(errand.errand_id).status == "cancelled"
