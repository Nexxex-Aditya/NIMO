"""Disjoint-set union over confirmed-same rows — `03` §1a, `specs/registry.md` §5.

`03` §1a's argument for this over a learned GNN, in one line: "these N rows are
the same physical product" is symmetric and transitive by construction, which
is what disjoint-set union computes exactly, with no training data, in
`O(n·α(n))`, correct immediately at n=412 and unchanged as the catalog grows.

Determinism is a requirement here, not a nicety (`04` §5). The registry
persists across runs, so components computed in a different order on Tuesday
must equal the ones computed on Monday or `entity_id` stops being stable.
"""


class UnionFind:
    """Union by size, path compression, deterministic representatives.

    The representative of a set is always its **smallest member by sort
    order**, not whichever element happened to be inserted first. Union by
    size alone would make the representative depend on insertion order, and a
    registry whose entity membership depends on row ordering cannot produce a
    byte-identical re-run.
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._size: dict[str, int] = {}

    def add(self, member: str) -> None:
        if member not in self._parent:
            self._parent[member] = member
            self._size[member] = 1

    def find(self, member: str) -> str:
        self.add(member)
        root = member
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression, iterative — a recursive version would blow the
        # stack on a pathological chain and this runs over untrusted-length input.
        while self._parent[member] != root:
            self._parent[member], member = root, self._parent[member]
        return root

    def union(self, left: str, right: str) -> str:
        """Merge two sets, returning the resulting root."""
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return left_root
        if self._size[left_root] < self._size[right_root]:
            left_root, right_root = right_root, left_root
        self._parent[right_root] = left_root
        self._size[left_root] += self._size[right_root]
        return left_root

    def components(self) -> dict[str, list[str]]:
        """Every component, keyed by its deterministic representative.

        Members are sorted, and the key is the smallest member — so the result
        depends only on which unions happened, never on the order they were
        applied in. That property is what
        `test_components_are_order_independent` pins.
        """
        grouped: dict[str, list[str]] = {}
        for member in sorted(self._parent):
            grouped.setdefault(self.find(member), []).append(member)
        return {min(members): sorted(members) for members in grouped.values()}
