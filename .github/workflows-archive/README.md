# Workflows put away

GitHub runs only the files in `.github/workflows/`. The 24 files here were moved out on 2026-11-24
because none had run since 2026-09-28: most were one-off repairs for weeks 34 to 39, and the rest
are steps that the hourly round or the close-week button now runs itself (rehome, carry-excess,
move-staged, redate-to-week, free-seats). The Actions page lists the 20 that the weekly loop and
its repairs use.

Nothing was deleted. The Python each one calls is still in `backend/`. To use one again, move its
file back:

    git mv .github/workflows-archive/<name>.yml .github/workflows/<name>.yml

`backend/test_workflows.py` checks the shape of the files in `.github/workflows/` only, so check a
file you bring back against a current workflow (checkout and setup-python versions, the
`drive-write` concurrency group) before you run it.
