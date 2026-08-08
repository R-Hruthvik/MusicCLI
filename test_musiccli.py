"""Unit tests for the deepened MusicCLI modules (Track, radio, PlaybackSession).

Runs with `python -m unittest test_musiccli -v`. Uses stdlib unittest and a
fake radio fetcher / fake search so no network or subprocess is needed.
"""
import unittest
import subprocess
from collections import deque
from unittest import mock

import musiccli as m
from musiccli import Track, PlaybackSession


def T(title, artist='Artist', dur='3:00', vid='id', url=None):
    if url is None:
        url = f'https://www.youtube.com/watch?v={vid}'
    return Track(title=title, artist=artist, source='YouTube',
                 duration=dur, url=url, id=vid)


class TestTrackFromLine(unittest.TestCase):
    def test_full_line(self):
        line = "Song A ||| abc123 ||| Alice ||| AliceChan ||| MixPlaylist ||| 3:45"
        t = Track.from_line(line)
        self.assertEqual(t.title, 'Song A')
        self.assertEqual(t.id, 'abc123')
        self.assertEqual(t.artist, 'Alice')          # uploader wins over channel
        self.assertEqual(t.source, 'MixPlaylist')
        self.assertEqual(t.duration, '3:45')
        self.assertEqual(t.url, 'https://www.youtube.com/watch?v=abc123')

    def test_uploader_na_falls_back_to_channel(self):
        line = "Song B ||| xyz ||| NA ||| BobChan ||| NA ||| 2:00"
        t = Track.from_line(line)
        self.assertEqual(t.artist, 'BobChan')
        self.assertEqual(t.source, 'YouTube')        # playlist NA -> YouTube

    def test_missing_fields_give_unknown_artist(self):
        line = "Song C ||| zzz"
        t = Track.from_line(line)
        self.assertEqual(t.artist, 'Unknown Artist')
        self.assertEqual(t.source, 'YouTube')
        self.assertEqual(t.duration, '')

    def test_empty_title_defaulted(self):
        t = Track.from_line(" ||| qqq ||| Uploader ||| Ch")
        self.assertEqual(t.title, 'Untitled')


class TestDedupeKeys(unittest.TestCase):
    def test_tags_collapse(self):
        self.assertEqual(T('Song Name (Official Video)').core_key(),
                         T('Song Name - Official Audio').core_key())

    def test_feat_tail_stripped(self):
        self.assertEqual(T('Song Name (feat. Other Artist)').core_key(),
                         T('Song Name').core_key())

    def test_case_and_punct_insensitive(self):
        self.assertEqual(T('Hello   World!').core_key(),
                         T('hello world').core_key())


class TestRadioSeed(unittest.TestCase):
    def test_known_artist_uses_artist(self):
        self.assertEqual(radio_seed_seed(T('Whatever', artist='Dua Lipa')),
                         'Dua Lipa')

    def test_unknown_artist_uses_keywords(self):
        seed = radio_seed_seed(T('My Great Song Official', artist='Unknown Artist'))
        self.assertNotEqual(seed, '')
        self.assertIn('my', seed)


class TestFetchRadioTracks(unittest.TestCase):
    """fetch_radio_tracks is now pure *transport*: RD-mix retrieval + discovery."""

    def test_uses_rd_mix_before_search(self):
        seed = T('Hit', artist='Singer', vid='abc')
        rd = T('RD Track A', artist='Other', vid='r1')
        with mock.patch.object(m, '_run_ytdlp', return_value=[rd]):
            out = m.fetch_radio_tracks(seed, {})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].id, 'r1')

    def test_discovery_uses_mood_genre_seed(self):
        seed = T('Hit', artist='Singer', vid='abc')
        captured = {}
        def fake_search(query, max_results=8):
            captured['q'] = query
            return [T('Found', artist='Zed', vid='z1')]
        with mock.patch.object(m, 'search_youtube', fake_search):
            out = m.fetch_radio_tracks(seed, {'discovery': True, 'max': 8})
        self.assertIn(captured['q'], m._DISCOVERY_QUERIES)
        self.assertEqual(len(out), 1)

    def test_discovery_query_list_is_nonempty(self):
        self.assertTrue(m._DISCOVERY_QUERIES)

    def test_falls_back_to_artist_search_if_rd_empty(self):
        seed = T('Hit', artist='Singer', vid='abc')
        with mock.patch.object(m, '_run_ytdlp', return_value=[]), \
             mock.patch.object(m, 'search_youtube',
                               return_value=[T('Fallback', artist='Singer2', vid='f1')]):
            out = m.fetch_radio_tracks(seed, {})
        self.assertEqual(out[0].title, 'Fallback')


class TestUrlAndPlaylist(unittest.TestCase):
    def test_is_playlist_url(self):
        self.assertTrue(m.is_playlist_url('https://www.youtube.com/playlist?list=PLxyz'))
        self.assertTrue(m.is_playlist_url('https://www.youtube.com/watch?v=abc&list=PLxyz'))
        self.assertFalse(m.is_playlist_url('https://www.youtube.com/watch?v=abc'))
        self.assertFalse(m.is_url('search words'))

    def test_fetch_playlist_parses_tracks(self):
        lines = ['One ||| 1 ||| Arena ||| Ch ||| PL ||| 2:00',
                 'Two ||| 2 ||| Band ||| Ch ||| PL ||| 3:00']
        def fake_ytdlp(urls, max_results):
            return [Track.from_line(l) for l in lines]
        with mock.patch.object(m, '_run_ytdlp', side_effect=fake_ytdlp):
            res = m.fetch_playlist('https://youtu.be/PL', max_results=5)
        self.assertEqual([t.title for t in res], ['One', 'Two'])

    def test_fetch_single_returns_first(self):
        tracks = [T('Solo', artist='Solo', vid='s1')]
        with mock.patch.object(m, '_run_ytdlp', return_value=tracks):
            one = m.fetch_single('https://youtu.be/s1')
        self.assertIsNotNone(one)
        self.assertEqual(one.title, 'Solo')


class TestFormatting(unittest.TestCase):
    def test_fmt_views_compact(self):
        self.assertEqual(m.fmt_views('1234567'), '1.2M')
        self.assertEqual(m.fmt_views('9800000000'), '9.8B')
        self.assertEqual(m.fmt_views('5400'), '5K')
        self.assertEqual(m.fmt_views(''), '--')
        self.assertEqual(m.fmt_views('NA'), '--')

    def test_fmt_upload_date(self):
        self.assertEqual(m.fmt_upload_date('20240501'), '2024-05-01')
        self.assertEqual(m.fmt_upload_date(''), '')


class TestTrackExtras(unittest.TestCase):
    def test_from_line_parses_views_and_date(self):
        line = "Song ||| id1 ||| Alice ||| Ch ||| PL ||| 3:45 ||| 9876543 ||| 20240501"
        t = Track.from_line(line)
        self.assertEqual(t.views, '9876543')
        self.assertEqual(t.upload_date, '20240501')

    def test_from_line_without_extras(self):
        line = "Song ||| id1 ||| Alice ||| Ch ||| PL ||| 3:45"
        t = Track.from_line(line)
        self.assertEqual(t.views, '')
        self.assertEqual(t.upload_date, '')


class TestSelectSearchResults(unittest.TestCase):
    def test_collapses_reupload_same_artist(self):
        a = T('Song (Official Audio)', artist='X', vid='1')
        b = T('Song - Official Video', artist='X', vid='2')
        out = m.select_search_results([a, b], 10)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].id, '1')          # first (relevance) wins

    def test_keeps_covers_by_different_artists(self):
        a = T('Song', artist='Alice', vid='1')
        b = T('Song', artist='Bob', vid='2')
        out = m.select_search_results([a, b], 10)
        self.assertEqual(len(out), 2)

    def test_prefers_duplicate_with_duration(self):
        a = T('Song', artist='X', vid='1', dur='')
        b = T('Song', artist='X', vid='2', dur='3:00')
        out = m.select_search_results([a, b], 10)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].id, '2')          # replaced in place

    def test_drops_junk(self):
        t = Track(title='', artist='X', source='YouTube', duration='', url='', id='')
        out = m.select_search_results([t], 10)
        self.assertEqual(out, [])

    def test_respects_limit(self):
        out = m.select_search_results(
            [T(f'S{i}', artist='X', vid=str(i)) for i in range(5)], 3)
        self.assertEqual(len(out), 3)

    def test_preserves_relevance_order(self):
        out = m.select_search_results(
            [T(f'S{i}', artist='X', vid=str(i)) for i in range(3)], 10)
        self.assertEqual([t.title for t in out], ['S0', 'S1', 'S2'])


class TestSearchYouTube(unittest.TestCase):
    def test_returns_polished_results(self):
        raw = '\n'.join([
            "Song A (Official) ||| 1 ||| X ||| X ||| NA ||| 3:00 ||| 1000 ||| 20240501",
            "Song A - Official Video ||| 2 ||| X ||| X ||| NA ||| 3:00 ||| 900 ||| 20240501",
            "Song B ||| 3 ||| Y ||| Y ||| NA ||| 4:00 ||| 5000 ||| 20240401",
        ])
        proc = mock.Mock()
        proc.stdout = raw
        proc.stderr = ''
        with mock.patch.object(subprocess, 'run', return_value=proc):
            out = m.search_youtube('query here', max_results=5)
        self.assertEqual([t.title for t in out], ['Song A (Official)', 'Song B'])

    def test_max_results_respected(self):
        proc = mock.Mock()
        proc.stdout = '\n'.join(
            f"S{i} ||| {i} ||| X ||| X ||| NA ||| 3:00" for i in range(10))
        proc.stderr = ''
        with mock.patch.object(subprocess, 'run', return_value=proc):
            out = m.search_youtube('q', max_results=3)
        self.assertEqual(len(out), 3)




class TestRadioVariety(unittest.TestCase):
    """Direct tests for RadioVariety - variety rules in one place."""

    def test_absorb_drops_seen_core_keys(self):
        v = m.RadioVariety(seen={'song'}, recent=deque(), artist_last={}, artist_count={})
        t = T('Song', vid='id1')
        result = v.absorb([t])
        self.assertIn('song', v.seen)
        # Result will be empty because 'song' is already in seen
        self.assertEqual(len(result), 0)

    def test_absorb_drops_recent_ring_hits(self):
        v = m.RadioVariety(seen=set(), recent=deque(['hit'], maxlen=8), artist_last={}, artist_count={}, pos=1)
        t = T('Hit', vid='h1')
        result = v.absorb([t])
        self.assertEqual(len(result), 0)

    def test_absorb_drops_artist_min_separation(self):
        v = m.RadioVariety(seen=set(), recent=deque(), artist_last={'x': 1}, artist_count={'x': 1}, pos=2)
        t = T('X New', artist='X', vid='x1')
        result = v.absorb([t])
        self.assertEqual(len(result), 0)

    def test_absorb_respects_per_artist_cap(self):
        v = m.RadioVariety(seen=set(), recent=deque(), artist_last={}, artist_count={'x': 2}, pos=0)
        tracks = [T(f'T{i}', artist='X', vid=f't{i}') for i in range(3)]
        result = v.absorb(tracks)
        # With artist_count={'x': 2}, only 0 tracks should be added (cap is 2)
        self.assertEqual(len(result), 0)

    def test_absorb_prefers_new_artists(self):
        v = m.RadioVariety(seen=set(), recent=deque(), artist_last={}, artist_count={}, pos=0)
        repeat = T('Repeat', artist='X', vid='r')
        fresh = T('Fresh', artist='Y', vid='f')
        result = v.absorb([repeat, fresh])
        # fresh (Y) should queue before repeat (X) since Y is not in artist_count
        self.assertEqual(result[0].artist, 'Y')
        self.assertEqual(result[-1].artist, 'X')

    def test_dominated_returns_true_when_one_artist_dominates(self):
        v = m.RadioVariety(seen=set(), recent=deque(), artist_last={}, artist_count={}, pos=0)
        queue = [T('A1', artist='X'), T('A2', artist='X'), T('A3', artist='X'), T('B1', artist='Y')]
        self.assertTrue(v.dominated(queue))

    def test_dominated_returns_false_when_balanced(self):
        v = m.RadioVariety(seen=set(), recent=deque(), artist_last={}, artist_count={}, pos=0)
        queue = [T('A1', artist='X'), T('B1', artist='Y'), T('C1', artist='Z')]
        self.assertFalse(v.dominated(queue))

    def test_absorb_drops_no_url(self):
        v = m.RadioVariety(seen=set(), recent=deque(), artist_last={}, artist_count={}, pos=0)
        t = Track(title='No URL', artist='X', source='YouTube', duration='', url='', id='')
        result = v.absorb([t])
        self.assertEqual(len(result), 0)

class TestPlaybackSession(unittest.TestCase):
    def test_queue_after_selection(self):
        res = [T('A'), T('B'), T('C')]
        s = PlaybackSession(res, start_index=1)
        self.assertEqual(s.current().title, 'B')
        self.assertEqual([t.title for t in s._queue], ['C'])
        self.assertEqual(s._seen, {'a', 'b', 'c'})

    def test_advance_pops_queue_in_order(self):
        s = PlaybackSession([T('A'), T('B'), T('C')], start_index=0)
        s.remember(s.current())
        self.assertEqual(s.advance().title, 'B')
        self.assertEqual(s.advance().title, 'C')
        self.assertIsNone(s.advance())      # queue empty, radio off

    def test_radio_off_no_refill(self):
        s = PlaybackSession([T('A')], start_index=0, radio=False)
        s.remember(s.current())
        self.assertIsNone(s.advance())

    def test_back_rewinds(self):
        res = [T('A', vid='a1'), T('B', vid='b2'), T('C', vid='c3')]
        s = PlaybackSession(res, start_index=0)
        s.remember(s.current())          # A playing
        s.advance()                      # -> B
        s.remember(s.current())          # B playing
        back = s.back()                  # -> A
        self.assertEqual(back.title, 'A')
        self.assertEqual(s._queue[0].title, 'B')   # B pushed back to front

    def test_snapshot_is_detached_copy(self):
        s = PlaybackSession([T('A'), T('B')], start_index=0)
        s.remember(s.current())
        snap = s.snapshot()
        snap['queue'].append(T('ZZZ'))   # mutate the copy
        self.assertEqual([t.title for t in s._queue], ['B'])  # session untouched

    def test_radio_refill_skips_same_core_and_advances(self):
        seed = T('Hit', artist='Singer', vid='h1')
        fresh_new = T('Brand New Song', artist='Singer2', vid='n1')
        cover = T('Hit (Official Video)', artist='X', vid='c1')  # collapses to core 'hit'
        def fake_fetcher(seed_track, ctx):
            return [cover, fresh_new]
        s = PlaybackSession([seed], start_index=0, radio=True, fetcher=fake_fetcher)
        s.remember(seed)
        nxt = s.advance()
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.title, 'Brand New Song')   # cover skipped (same core)
        self.assertNotIn('hit', [t.core_key() for t in s._queue])

    def test_per_artist_cap_limits_batch(self):
        # 3 tracks by the same artist -> only ARTIST_MAX_PER_BATCH kept via variety
        # This is tested via RadioVariety.absorb directly
        pass  # covered by TestRadioVariety.test_absorb_respects_per_artist_cap

    def test_recent_ring_blocks_immediate_repeat(self):
        # This is tested via RadioVariety.absorb directly
        pass  # covered by TestRadioVariety.test_absorb_drops_recent_ring_hits

    def test_new_artist_preference_orders_first(self):
        # This is tested via RadioVariety.absorb directly
        pass  # covered by TestRadioVariety.test_absorb_prefers_new_artists

    def test_dominated_batch_triggers_discovery(self):
        def ff(seed, ctx):
            if ctx.get('discovery'):
                return [T('D1', artist='Other', vid='d1')]
            return [T('S1', artist='Same', vid='s1'), T('S2', artist='Same', vid='s2')]
        s = PlaybackSession([T('start', artist='start', vid='st')], start_index=0,
                            radio=True, fetcher=ff)
        s.remember(s.current())
        nxt = s.advance()
        self.assertEqual(nxt.artist_key(), 'other')   # discovery broke the single-artist run


def radio_seed_seed(track):
    return m.radio_seed(track)


if __name__ == '__main__':
    unittest.main()
