class UpdateFailed(Exception): ...
class DataUpdateCoordinator:
    def __class_getitem__(cls, item): return cls
    def __init__(self, *a, **k): pass
class CoordinatorEntity:
    def __class_getitem__(cls, item): return cls
