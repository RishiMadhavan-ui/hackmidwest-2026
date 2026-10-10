from provenance.sink import MemorySink, emit_all


def test_one_broken_sink_does_not_stop_the_others():
  class Broken:
    def emit(self, event):
      raise RuntimeError("boom")

  good = MemorySink()
  emit_all([Broken(), good], {"type": "x"})
  assert good.events == [{"type": "x"}]
