class _CV:
    @staticmethod
    def ensure_list(v): return v
    string = str
    time = str
    boolean = bool
config_validation = _CV()
class _DR:
    @staticmethod
    def async_get(hass): return None
device_registry = _DR()
