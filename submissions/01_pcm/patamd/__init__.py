"""patamd - AMD EPYC (Zen 4) single-core / multi-core versions of the top
patzstd configurations, plus new back ends (pcm context mixing, bzip3 BWT).
patzstd is untouched; see patamd/codec.py and results/IDEAS.md section 11."""
from .codec import (compress, decompress, decompress_to_memory, iter_members,
                    members_from_path, parse_mode, PzstError)
