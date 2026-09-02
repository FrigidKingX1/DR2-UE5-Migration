from dataclasses import dataclass, field
from typing import List


@dataclass
class FloatList:
    count: int = 0
    step: float = 0.0
    items: List[float] = field(default_factory=list)

    def to_dict(self):
        return {"count": self.count, "step": self.step, "items": list(self.items)}

    @classmethod
    def from_dict(cls, d):
        return cls(int(d["count"]), float(d["step"]), [float(x) for x in d["items"]])