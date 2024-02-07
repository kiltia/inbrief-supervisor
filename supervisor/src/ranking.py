import json
import logging
from functools import reduce

from rb_tocase import Case

from shared.entities import Source

logger = logging.getLogger("app")


class AbstractScorer:
    def get_metrics(self, scores):
        return list(map(self.key, scores))

    def change_scores(self, scores, boost=1):
        metrics = self.get_metrics(scores)
        max_score = max(metrics)

        if max_score == 0:
            max_score = 1

        return list(
            map(
                lambda pair: (
                    (pair[0] / max_score) * boost + pair[1][0],
                    pair[1][1],
                ),
                zip(metrics, scores, strict=True),
            )
        )

    @classmethod
    def get_label(self):
        return Case.to_snake(self.__name__)


class SizeScorer(AbstractScorer):
    def __init__(self):
        self.key = lambda x: len(x[1][1])


class ReactionScorer(AbstractScorer):
    def __init__(self):
        self.key = lambda x: self._get_story_score(x[1][1])

    def _get_reactions(self, entity: Source):
        if entity.reactions is None:
            return 0

        reactions = json.loads(entity.reactions)

        count = 0
        for reaction_entry in reactions:
            count += reaction_entry["count"]

        return count

    def _get_story_score(self, story_entry):
        return reduce(
            lambda acc, y: acc + self._get_reactions(y), story_entry, 0
        )


class CommentScorer(AbstractScorer):
    def __init__(self):
        self.key = lambda x: self._get_story_score(x[1][1])

    def _get_comments(self, entity: Source):
        return len(entity.comments) if entity.comments else 0

    def _get_story_score(self, story_entry):
        return reduce(
            lambda acc, y: acc + self._get_comments(y), story_entry, 0
        )


class ViewScorer(AbstractScorer):
    def __init__(self):
        self.key = lambda x: self._get_story_score(x[1][1])

    def _get_story_score(self, story_entry):
        return reduce(lambda acc, y: acc + y.views, story_entry, 0)


class Ranker:
    def __init__(self, scorers):
        self.scorers = scorers

    def _get_scorers(self, required_scorers=None):
        if not required_scorers:
            return self.scorers
        return list(
            filter(lambda x: x.get_label() in required_scorers), self.scorers
        )

    def get_sorted(
        self,
        stories,
        weights,
        required_scorers=None,
        return_scores=False,
    ):
        current_scores = list(map(lambda x: (0.0, x), stories))
        scorers = self._get_scorers(required_scorers)
        for scorer in scorers:
            current_scores = scorer.change_scores(
                current_scores, boost=weights[scorer.get_label()]
            )

        sorted_scores = sorted(
            current_scores, key=lambda x: x[0], reverse=True
        )

        printable_scores = list(
            map(
                lambda x: (x[0], x[1][0]),
                sorted_scores,
            )
        )

        logger.debug(f"Ranking results: {printable_scores}")
        if not return_scores:
            sorted_scores = list(map(lambda x: x[1], sorted_scores))

        return sorted_scores


def init_scorers():
    return [scorer() for scorer in AbstractScorer.__subclasses__()]
