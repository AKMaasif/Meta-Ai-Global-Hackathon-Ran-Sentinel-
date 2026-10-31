import pytest
from fastapi import HTTPException, Response

from app import main


def login(email, pw, portal):
    return main.login(main.Login(email=email, password=pw, portal=portal), Response())


def test_accounts_sign_in_on_their_own_portal():
    s = main.settings
    assert login(s.ops_email, s.ops_password, "ops")["ok"]
    assert login(s.customer_email.upper(), s.customer_password, "connect")["name"] == "Northstar customer"


def test_wrong_portal_points_to_the_right_one():
    s = main.settings
    with pytest.raises(HTTPException) as e:
        login(s.customer_email, s.customer_password, "ops")
    assert e.value.status_code == 403 and e.value.detail["portal"] == "connect"
    with pytest.raises(HTTPException) as e:
        login(s.ops_email, s.ops_password, "connect")
    assert e.value.detail["portal"] == "ops"
    with pytest.raises(HTTPException) as e:
        login(s.customer_email, "wrong", "ops")
    assert e.value.status_code == 401 and "incorrect" in e.value.detail
