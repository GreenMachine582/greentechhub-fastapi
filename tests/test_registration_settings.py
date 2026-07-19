from greentechhub_fastapi.registration._settings import read_str_setting


class _Obj:
    pass


def test_read_str_setting_returns_declared_value():
    obj = _Obj()
    obj.AUTH_ADAPTER = "forward_auth"
    assert read_str_setting(obj, "AUTH_ADAPTER", "local") == "forward_auth"


def test_read_str_setting_falls_back_to_default_when_missing():
    obj = _Obj()
    assert read_str_setting(obj, "AUTH_ADAPTER", "local") == "local"


def test_read_str_setting_falls_back_to_default_when_falsy():
    obj = _Obj()
    obj.AUTH_ADAPTER = ""
    assert read_str_setting(obj, "AUTH_ADAPTER", "local") == "local"
