class Invalid(Exception): ...
class Schema:
    def __init__(self, *a, **k): pass
    def __call__(self, v): return v
def All(*a, **k): return lambda v: v
def Coerce(t): return t
def Range(**k): return lambda v: v
def In(x): return lambda v: v
def Required(k, **kw): return k
def Optional(k, **kw): return k
