class ConfigEntryState:
    LOADED = "loaded"
class ConfigEntry(dict):
    def __class_getitem__(cls, item): return cls
