"""回归测试：这些用例全部来自实测踩过的坑，不是想象出来的边界。

跑法：PYTHONPATH=src python3 -B -m unittest discover -s tests -v
（不依赖 pytest，因为项目本身零依赖；`python -B` 是绕开沙箱里写不了 pycache 的问题）
"""

import os
import time
import unittest
from types import SimpleNamespace

from freebie import extract, report, seeds
from freebie.config import Config
from freebie.models import Item
from freebie.pipeline import _hint_offset, in_window
from freebie.config import Config
from freebie.ranking import score

NOW = time.struct_time((2026, 10, 28, 12, 0, 0, 0, 0, -1))


class FreeDetectionTest(unittest.TestCase):
    def test_200_yuan_is_not_free(self):
        """实测 bug：『满200元减80元』里的 0元 曾被判成免费，害得惠民券被标成免票。"""
        self.assertFalse(extract.FREE_RE.search("设置满100元减40元、满200元减80元两档惠民券"))

    def test_zero_yuan_is_free(self):
        self.assertTrue(extract.FREE_RE.search("门票 0 元"))
        self.assertTrue(extract.FREE_RE.search("零元入场"))

    def test_free_in_footer_is_junk(self):
        body = "活动介绍\n免费创建活动\n报名方式：现场排队"
        self.assertNotIn("免费创建", extract._filter_lines(body))


class BookingTest(unittest.TestCase):
    def test_booking_label_is_not_a_requirement(self):
        """『预约方式：免费开放，无需预约』曾让 needs_booking 变 True。"""
        self.assertFalse(extract.BOOKING_RE.search("预约方式：免费开放，无需预约"))

    def test_real_booking_still_detected(self):
        self.assertTrue(extract.BOOKING_RE.search("预约方式：关注公众号预约"))
        self.assertTrue(extract.BOOKING_RE.search("需提前预约，名额有限"))


class DateTest(unittest.TestCase):
    def test_cross_month_range(self):
        """『10月31日至11月1日』曾被截成 10.31-11，产出一个不存在的日期。"""
        hints = extract.extract_fields("活动时间为 10月31日至11月1日 在城市绿心森林公园举行")["date_hints"]
        self.assertIn("10.31-11.1", hints)
        self.assertNotIn("10.31-11", hints)

    def test_year_fragment_is_dropped(self):
        hints = extract.extract_fields("2026-10-11 17:04 来源：北京发布")["date_hints"]
        self.assertFalse([h for h in hints if h.startswith("26.")])

    def test_metadata_line_not_summary(self):
        text = "日期：2026-09-20 11:02 来源：北京发布\n本届展演季覆盖京剧、话剧、儿童剧等六大类剧目，全部免费入场，无需预约。"
        s = extract.summarize(text)
        self.assertNotIn("来源：", s)
        self.assertIn("六大类剧目", s)


class VenueTest(unittest.TestCase):
    def test_venue_drops_sentence_tail(self):
        text = "绿心花朝游园会\n在城市绿心森林公园举行中\n全程免费"
        self.assertEqual(extract._venue(text), "城市绿心森林公园")

    def test_venue_skips_navigation(self):
        text = "首页 > 活动\n合作 -->活动行学院\n真实场地：国家大剧院"
        self.assertNotIn("-->", extract._venue(text))


class WindowTest(unittest.TestCase):
    def test_hint_offset(self):
        self.assertEqual(_hint_offset("10.31", NOW), 3)
        self.assertEqual(_hint_offset("本周末", NOW), 0)

    def test_expired_is_dropped(self):
        """北师大开放日是 5 月 23 日，不该出现在 10 月的周报里。"""
        it = Item(url="u", title="t", date_hints=["5.23"])
        ok, why = in_window(it, Config(city="北京"), NOW)
        self.assertFalse(ok)
        self.assertEqual(why, "已过期")

    def test_no_date_is_kept_but_flagged(self):
        it = Item(url="u", title="t", date_hints=[])
        ok, why = in_window(it, Config(city="北京"), NOW)
        self.assertTrue(ok)
        self.assertEqual(why, "未标时间")


class RankingTest(unittest.TestCase):
    def test_free_beats_full_price(self):
        """免费条目要压过「原价票」——否则周报第一屏全是买票广告。"""
        free = Item(url="a", title="t", is_free=True, text_len=2000)
        paid = Item(url="b", title="t", is_free=False, prices=[380], text_len=2000)
        self.assertGreater(score(free, NOW), score(paid, NOW))

    def test_discount_anchored_once(self):
        """¥380→¥30 只该按折价加一次分（实测重复计分导致 53 分）。

        92% 折扣的付费票压过一张普通免费展是合理的，但分数必须可复算：
        15（低价）+ 25（折价上限）+ 5（正文长）= 45，不该再多出 8。
        """
        paid = Item(url="b", title="t", is_free=False, prices=[30], original_price=380, text_len=2000)
        self.assertEqual(score(paid, NOW), 45.0)


class SeedsTest(unittest.TestCase):
    def test_parse_beijing_seed(self):
        path = os.path.join("seeds", "beijing.yaml")
        with open(path, "r", encoding="utf-8") as f:
            s = seeds.parse(f.read(), path)
        self.assertEqual(s.city, "北京")
        self.assertGreaterEqual(len(s.urls()), 4)
        self.assertTrue(all(u.startswith("http") for u in s.urls()))
        self.assertTrue(s.queries)

    def test_unknown_city_returns_none(self):
        self.assertIsNone(seeds.find("火星"))



class DetailPageTest(unittest.TestCase):
    """平台详情页（活动行/广图）专属的坑，都是 2026-10-28 实测撞上的。"""

    def test_generic_title_falls_back_to_content(self):
        """广图页面 <title> 只写「活动详情」，进周报等于没标题。"""
        text = "【广州公益阅读】浙韵新声·粤继潇湘——浙派青年古琴名家名曲音乐会\n活动地点：广州图书馆"
        self.assertEqual(
            extract._content_title(text),
            "【广州公益阅读】浙韵新声·粤继潇湘——浙派青年古琴名家名曲音乐会",
        )

    def test_explicit_no_booking_wins(self):
        """「免门票免预约」要压过页面里的「预约入口」推荐链接，否则误报需预约。"""
        f = extract.extract_fields("活动在复兴岛举办，免门票免预约，预约入口见文末")
        self.assertFalse(f["needs_booking"])

    def test_labelled_iso_date(self):
        f = extract.extract_fields("活动时间：2026-11-08 14:30 开演")
        self.assertIn("11.8", f["date_hints"])

    def test_publish_time_is_not_event_date(self):
        f = extract.extract_fields("发布时间：2026-10-28 10:48 来源：某站")
        self.assertEqual(f["date_hints"], [])

    def test_recommend_link_is_not_venue(self):
        text = "上海大歌剧院入场参观预约方式2026（预约入口+优惠政策）"
        self.assertEqual(extract._venue(text), "")



class TitleSuffixTest(unittest.TestCase):
    def test_site_suffix_trimmed(self):
        """og:title 带站点名（`…攻略来啦_北京时间`），进周报太长。"""
        self.assertEqual(extract._strip_site_suffix("拍红叶、逛市集、做手作！游园会攻略来啦_北京时间"),
                         "拍红叶、逛市集、做手作！游园会攻略来啦")

    def test_short_title_untouched(self):
        self.assertEqual(extract._strip_site_suffix("展览_北京"), "展览_北京")



class DedupeKeyTest(unittest.TestCase):
    """去重键必须稳定：实测同一 URL 两次抓取，标题和日期都会漂（页面偶尔吐空壳）。"""

    def test_same_url_same_key(self):
        a = Item(url="https://x/1", title="绿心花朝游园会", date_hints=["10.31-11.1"])
        b = Item(url="https://x/1", title="（空壳页）", date_hints=[])
        self.assertEqual(a.key, b.key)

    def test_different_urls_differ(self):
        a = Item(url="https://x/1", title="免费活动汇总")
        b = Item(url="https://x/2", title="免费活动汇总")
        self.assertNotEqual(a.key, b.key)

    def test_no_url_falls_back_to_title(self):
        self.assertEqual(Item(title="某活动").key, "某活动")


if __name__ == "__main__":
    unittest.main()


ROUNDUP = """2026北京11月市集活动时间地点及门票- 北京本地宝
北平秋市
活动时间：11月6日–11月8日11:00-20:00
活动地点：北京市东城区东四南大街15号
活动亮点：用当代生活美学，重新翻译文人笔下的秋日生活质感
门票：免费
“不畅销”图书市集
活动时间：持续至11月3日
活动地点：北京西单更新场B1水之中庭
门票：免费
怪兽超市市集
活动时间：10月31日~11月1日 每日10:30-23:00
活动地点：北京市海淀区学清路38号BOM嘻番里3F
门票：60元
"""


class RoundupTest(unittest.TestCase):
    """一页十几场的汇总页，必须拆成多条——否则「条目太少」永远治不好。"""

    def test_one_page_becomes_many_events(self):
        evs = extract.roundup_events(ROUNDUP)
        self.assertEqual(len(evs), 3)
        self.assertEqual([e["title"] for e in evs], ["北平秋市", "“不畅销”图书市集", "怪兽超市市集"])

    def test_each_event_keeps_its_own_date_and_price(self):
        evs = extract.roundup_events(ROUNDUP)
        self.assertEqual(evs[0]["fields"]["date_hints"], ["11.6-11.8"])
        self.assertEqual(evs[1]["fields"]["date_hints"], ["11.3"])
        self.assertTrue(evs[0]["is_free"])
        self.assertFalse(evs[2]["is_free"])
        self.assertEqual(evs[2]["prices"], [60.0])

    def test_venue_is_not_the_whole_label_line(self):
        evs = extract.roundup_events(ROUNDUP)
        self.assertEqual(evs[2]["venue"], "北京市海淀区学清路38号BOM嘻番里3F")

    def test_normal_article_is_not_split(self):
        text = "活动时间：11月1日 14:00\n活动地点：民族剧院\n门票：免费"
        self.assertEqual(extract.roundup_events(text), [])


class RenderTest(unittest.TestCase):
    """排版是用户直接看到的东西：分组、链接、丢弃条目都要对。"""

    NOW = time.localtime(time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1)))

    def _item(self, title, hints, price=None, free=True, **kw):
        it = Item(
            url=kw.pop("url", "https://item.btime.com/x"),
            title=title,
            is_free=free,
            prices=[] if free else ([price] if price else []),
            date_hints=hints,
            venue=kw.pop("venue", ""),
            summary=kw.pop("summary", ""),
            needs_booking=kw.pop("needs_booking", False),
            deadline=kw.pop("deadline", ""),
            notes=kw.pop("notes", ""),
            text_len=800,
        )
        return it

    def _render(self, items, dropped=(), notes=()):
        res = SimpleNamespace(
            items=items,
            notes=list(notes),
            stats={"candidates": 3, "fetched": 4, "kept": len(items), "dropped": {"超出窗口": 1}},
            dropped_items=list(dropped),
        )
        return report.render(res, Config(city="北京"), now=self.NOW)

    def test_groups_by_when_not_by_score(self):
        out = self._render(
            [
                self._item("这周的活动", ["10.31"]),
                self._item("下周的活动", ["11.9"]),
                self._item("没写时间的活动", []),
            ]
        )
        self.assertLess(out.index("这周就能去"), out.index("之后几天"))
        self.assertLess(out.index("之后几天"), out.index("时间没写清"))
        self.assertIn("▎这周就能去（1）", out)

    def test_link_is_markdown_with_readable_label(self):
        out = self._render([self._item("绿心花朝游园会", ["10.31"])])
        self.assertIn("[北京时间](https://item.btime.com/x)", out)
        self.assertNotIn("→ https://", out.replace("[北京时间]", ""))  # 不再裸贴 URL

    def test_long_title_is_cut_and_action_line_exists(self):
        out = self._render([self._item("通州不远 周末首选 | 拍红叶、逛市集、做手作、看演出、逛市集（内含地铁接驳与停车指南）", ["10.31"])])
        self.assertIn("…", out)
        self.assertIn("不用预约，直接去", out)

    def test_booking_items_say_so(self):
        out = self._render([self._item("河畔时光音乐会", ["11.1"], needs_booking=True)])
        self.assertIn("要预约，点原文找入口", out)

    def test_dropped_items_are_listed(self):
        out = self._render(
            [self._item("留下的", ["10.31"])],
            dropped=[("惠民观演季", "超出窗口", "11.15")],
        )
        self.assertIn("也抓到了，但不在本周窗口", out)
        self.assertIn("惠民观演季（超出窗口，11.15）", out)

    def test_split_links_point_back_to_the_page(self):
        out = self._render([self._item("怪兽超市市集", ["10.31"], url="https://m.bj.bendibao.com/x.html#3")])
        self.assertIn("[本地宝](https://m.bj.bendibao.com/x.html)", out)
        self.assertNotIn("#3)", out)
