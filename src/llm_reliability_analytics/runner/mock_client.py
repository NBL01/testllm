import hashlib
import random
from dataclasses import dataclass


@dataclass
class MockLLMClient:
    """Simple mock LLM for demo/test runner usage."""

    mode: str = "deterministic"
    seed: int = 42
    failure_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.mode not in {"deterministic", "semi_random"}:
            raise ValueError("mode must be 'deterministic' or 'semi_random'")
        self._random = random.Random(self.seed)

    def generate(self, prompt: str) -> str:
        if self.mode == "semi_random" and self.failure_rate > 0:
            if self._random.random() < self.failure_rate:
                raise RuntimeError("mock_generation_error")

        base_answer = self._rule_based_answer(prompt)
        if base_answer is None:
            base_answer = self._fallback_answer(prompt)

        if self.mode == "semi_random" and self._random.random() < 0.25:
            return self._perturb(base_answer)
        return base_answer

    def _rule_based_answer(self, prompt: str) -> str | None:
        normalized = prompt.strip().lower()
        rules: list[tuple[str, str]] = [
            ("what is 2 + 2", "4"),
            ("compute 15 * 6", "90"),
            ("derivative of x^2", "2x"),
            ("capital of japan", "Tokyo"),
            ("who wrote pride and prejudice", "Jane Austen"),
            ("process plants use to convert light", "Photosynthesis"),
            ("sparrows have wings", "Yes"),
            ("binary search", "O(log n)"),
            ("keyword defines a function in python", "def"),
            ("translate to english: 'hola mundo'", "Hello world"),
            ("translate to english: 'je suis étudiant.'", "I am a student."),
        ]

        for needle, answer in rules:
            if needle in normalized:
                return answer
        return None

    def _fallback_answer(self, prompt: str) -> str:
        candidates = [
            "Yes",
            "No",
            "I am not sure.",
            "This requires more context.",
            "42",
            "Paris",
        ]
        digest = hashlib.sha256(f"{self.seed}:{prompt}".encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(candidates)
        return candidates[index]

    def _perturb(self, answer: str) -> str:
        perturbations = [
            f"{answer}.",
            answer.lower(),
            f"{answer} (approx)",
        ]
        return self._random.choice(perturbations)
