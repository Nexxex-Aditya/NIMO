"""TF-IDF nearest-centroid module classifier — `specs/classify.md` §4, §5.

Chosen over multinomial NB, complement NB and k-NN, all measured leave-one-out
over the real 412-row `dev` sheet (`specs/classify.md` §4). NB is the
instructive loser: it matches on overall accuracy and is 11 macro points
worse, buying head accuracy by collapsing the long tail — the exact trap
`01` §9 warns about.
"""

from collections import defaultdict
from dataclasses import dataclass

from nimo.classify.config import ClassifyConfig
from nimo.classify.features import (
    char_ngrams,
    cosine,
    document_frequencies,
    inverse_document_frequencies,
    l2_normalize,
    sum_vectors,
    tfidf_vector,
)
from nimo.contracts import ModulePrediction, ProductQuery


class ClassifierError(Exception):
    """The classifier was asked to do something structurally impossible."""


def classified_text(query: ProductQuery, config: ClassifyConfig) -> str:
    """The exact text the classifier reads. `specs/classify.md` §3.

    `desc_clean` — P3's output — and nothing else by default. `desc_clean`
    beats `desc_raw` by 3.2 points overall and 5.8 macro on identical
    features, which is independent, downstream-task evidence for P3's junk
    stripping rather than an assertion about it.

    BRAND is behind `use_brand`, default false: including it costs 7.5 points
    overall and 3.5 macro (`config/classify.yaml`). Brand does not predict
    module — ORAL-B makes brushes, refill heads and toothpaste alike.
    """
    if config.use_brand:
        return f"{query.brand} {query.desc_clean}"
    return query.desc_clean


@dataclass(frozen=True)
class ModuleClassifier:
    """A fitted nearest-centroid model.

    A frozen dataclass rather than a pydantic contract: it holds fitted state
    and has behavior, so it is an implementation object of this module, not a
    value crossing a boundary (`04` §3). What crosses the boundary is
    `ModulePrediction`.
    """

    config: ClassifyConfig
    idf: dict[str, float]
    centroids: dict[str, dict[str, float]]
    training_vectors: dict[str, dict[str, float]]
    training_labels: dict[str, str]

    @property
    def modules(self) -> list[str]:
        """Modules this model can emit, sorted. Never a set — `04` §5 forbids
        relying on set order, and this feeds tie-breaking."""
        return sorted(self.centroids)

    @classmethod
    def fit(
        cls,
        queries: list[ProductQuery],
        labels: list[str],
        config: ClassifyConfig,
    ) -> "ModuleClassifier":
        """Fit on positionally aligned queries and `MODULE` labels.

        `labels[i]` is the ground-truth module of `queries[i]`, the same shape
        `nimo.gold.sample.stratify_by_module` consumes and
        `nimo.loader.load_module_labels` produces.
        """
        if len(queries) != len(labels):
            raise ClassifierError(
                f"queries and labels must be positionally aligned; got {len(queries)} "
                f"queries and {len(labels)} labels"
            )
        if not queries:
            raise ClassifierError(
                "cannot fit on zero rows — an empty model would predict nothing and "
                "report no error at predict time (`04` §4)"
            )

        documents = [char_ngrams(classified_text(q, config), config.ngram_sizes) for q in queries]
        idf = inverse_document_frequencies(document_frequencies(documents), len(documents))

        vectors = [tfidf_vector(document, idf) for document in documents]
        by_module: dict[str, list[dict[str, float]]] = defaultdict(list)
        for vector, label in zip(vectors, labels, strict=True):
            by_module[label].append(vector)

        return cls(
            config=config,
            idf=idf,
            centroids={
                module: l2_normalize(sum_vectors(module_vectors))
                for module, module_vectors in by_module.items()
            },
            training_vectors={q.row_uid: v for q, v in zip(queries, vectors, strict=True)},
            training_labels={q.row_uid: label for q, label in zip(queries, labels, strict=True)},
        )

    def score(self, query: ProductQuery) -> list[tuple[float, str]]:
        """Every module's cosine, best first. Ties broken by module name
        ascending — never by dict or set iteration order (`04` §5)."""
        vector = tfidf_vector(
            char_ngrams(classified_text(query, self.config), self.config.ngram_sizes), self.idf
        )
        return sorted(
            ((cosine(vector, self.centroids[module]), module) for module in self.centroids),
            key=lambda scored: (-scored[0], scored[1]),
        )

    def predict(self, query: ProductQuery) -> ModulePrediction:
        """Classify one row. Always emits a module — stage `[5]` is the
        fallback path (`03` §4 stage 5) and a fallback that abstains is not
        one. Trust is carried on `confidence`, not by declining to answer."""
        scored = self.score(query)
        confidence, module = scored[0]
        runner_up = scored[1][1] if len(scored) > 1 else None
        runner_up_gap = confidence - scored[1][0] if len(scored) > 1 else 0.0
        nearest_uid, nearest_similarity = self.nearest_example(query)
        return ModulePrediction(
            row_uid=query.row_uid,
            module=module,
            confidence=confidence,
            runner_up=runner_up,
            runner_up_gap=runner_up_gap,
            nearest_example_row_uid=nearest_uid,
            nearest_example_similarity=nearest_similarity,
            source="text_baseline",
        )

    def nearest_example(self, query: ProductQuery) -> tuple[str | None, float]:
        """The closest labelled training row, and its cosine.

        This is the transparency surface (`03` §3, `specs/classify.md` §5): a
        char-4-gram weight vector explains nothing to a human, but "it most
        resembles `dev:12` `aquafresh whitening pump 100ml`, which is labelled
        that module" is a citation a person can check by opening the row.

        The query's own `row_uid` is excluded, so calling this on a training
        row cites its nearest *neighbour* rather than itself.
        """
        vector = tfidf_vector(
            char_ngrams(classified_text(query, self.config), self.config.ngram_sizes), self.idf
        )
        candidates = [
            (cosine(vector, train_vector), row_uid)
            for row_uid, train_vector in self.training_vectors.items()
            if row_uid != query.row_uid
        ]
        if not candidates:
            return None, 0.0
        similarity, row_uid = max(candidates, key=lambda scored: (scored[0], scored[1]))
        return row_uid, similarity

    def unseen_scores(
        self, query: ProductQuery, absent_modules: list[str]
    ) -> list[tuple[float, str]]:
        """Score a row against modules the model has no examples of, by their
        NAMES. **Recorded, never acted on** — `specs/classify.md` §6.

        Measured: module names encode the form axis in category jargon
        (`KITS`, `MULTI DOSE`, `FOAM/GEL/LIQUID/PASTE`) that retail
        descriptions never use, so this resolves the product family and then
        guesses the form — "x-press dental stain remover" scores highest on
        `TOOTH STAIN REMOVERS - KITS`. On `qa` at the most generous useful
        margin, roughly 4 of 11 routes are right. There is deliberately no
        routing code here; a later stage holding an actual product page can
        use this as a hint.
        """
        vector = tfidf_vector(
            char_ngrams(classified_text(query, self.config), self.config.ngram_sizes), self.idf
        )
        name_vectors = {
            module: tfidf_vector(char_ngrams(module, self.config.ngram_sizes), self.idf)
            for module in absent_modules
        }
        return sorted(
            ((cosine(vector, name_vectors[module]), module) for module in name_vectors),
            key=lambda scored: (-scored[0], scored[1]),
        )
