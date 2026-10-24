"""TikTok FILE_UPLOAD chunk plan (media transfer guide).

- files up to 64 MB go up as a single chunk the size of the file;
- larger files use fixed chunks (5–64 MB); total = floor(size / chunk) and the last
  chunk absorbs the remainder (it may be up to 128 MB); at most 1000 chunks.
"""

from dataclasses import dataclass

MB = 1024 * 1024
SINGLE_CHUNK_MAX = 64 * MB
DEFAULT_CHUNK = 10 * MB
MAX_CHUNKS = 1000
MAX_FILE = 4 * 1024 * MB


@dataclass(frozen=True)
class ChunkPlan:
    video_size: int
    chunk_size: int
    total_chunks: int

    def byte_range(self, index: int) -> tuple[int, int]:
        """Inclusive (start, end) for chunk `index`, as used in Content-Range."""
        start = index * self.chunk_size
        last = index == self.total_chunks - 1
        end = self.video_size - 1 if last else start + self.chunk_size - 1
        return start, end


def plan_chunks(video_size: int, chunk_size: int = DEFAULT_CHUNK) -> ChunkPlan:
    if video_size <= 0:
        raise ValueError("empty file")
    if video_size > MAX_FILE:
        raise ValueError("file exceeds TikTok's 4 GB limit")
    if video_size <= SINGLE_CHUNK_MAX:
        return ChunkPlan(video_size, video_size, 1)
    total = video_size // chunk_size
    if total > MAX_CHUNKS:
        chunk_size = -(-video_size // MAX_CHUNKS)
        total = video_size // chunk_size
    return ChunkPlan(video_size, chunk_size, total)
