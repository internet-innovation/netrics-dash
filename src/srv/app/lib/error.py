class DependencyError(ModuleNotFoundError):
    pass


class ExplicitDependencyError(DependencyError):

    @classmethod
    def make_default(cls, target):
        return cls(target, f"missing required package {target!r}: "
                           "app misconfigured or misinstalled")

    def __init__(self, target, message):
        super().__init__(target, message)
        self.target = target


class ImplicitDependencyError(DependencyError):

    @classmethod
    def make_default(cls, target):
        return cls(f"failed to import {target!r}: app misconfigured or misinstalled")

    def __init__(self, message):
        super().__init__(message)
