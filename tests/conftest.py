import pytest

from haath.models import Segment, Transcript


def make_transcript(lines: list[tuple[float, str]], duration: float | None = None) -> Transcript:
    segs = []
    for i, (start, text) in enumerate(lines):
        end = lines[i + 1][0] if i + 1 < len(lines) else start + 5
        segs.append(Segment(id=i, start=start, end=end, text=text))
    return Transcript(language="hi", duration=duration or segs[-1].end, segments=segs)


@pytest.fixture
def hindi_transcript() -> Transcript:
    return make_transcript(
        [
            (0.0, "आज हम दाल बाटी बनाएंगे, तुम्हारे नाना जी को बहुत पसंद थी।"),
            (6.5, "सबसे पहले एक मुट्ठी आटा लो, और अंदाज़ से नमक।"),
            (14.2, "फिर थोड़ा सा हल्दी डालो, जब तक खुशबू न आए।"),
            (22.0, "ghee daalo, jab tak tel chhod de masala, tab tak bhuno."),
            (31.0, "Dhakkan mat kholna beech mein!"),
            (38.5, "फिर थोड़ा सा हल्दी दाल में भी।"),
        ]
    )
