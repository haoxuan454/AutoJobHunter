import json
from pathlib import Path
from threading import Event
from unittest import TestCase
from unittest.mock import patch

from bosshunter.collection.base import CollectionBlockedError, CollectionError, CollectorHooks
from bosshunter.collection.models import PlatformCollectionRequest
from bosshunter.collection.platforms.zhilian import (
    JD_CLASSES,
    JS_EXTRACT_DETAIL,
    JS_EXTRACT_LIST,
    ZhilianBrowser,
    ZhilianCollector,
    _analyze_api_response,
    _wait_for_rendered_list,

    _ApiRateLimiter,
    _reason_code_for,
    _source_job_id,
    get_zhilian_city_code,
    load_zhilian_city_snapshot,
    parse_zhilian_detail_html,
    parse_zhilian_list_html,
)


FIXTURES = Path(__file__).parent / "fixtures"


class ZhilianFixtureTests(TestCase):
    def setUp(self):
        self._patches = [
            patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=True),
            patch("bosshunter.collection.platforms.zhilian.should_take_day_off", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_city_snapshot_is_local_and_not_shared_with_boss_codes(self):
        snapshot = load_zhilian_city_snapshot()
        self.assertEqual(snapshot["schema"], "bosshunter.zhilian_cities.v1")

        self.assertGreaterEqual(len(snapshot["cities"]), 10)
        self.assertEqual(get_zhilian_city_code("北京"), "530")
        self.assertEqual(get_zhilian_city_code("北京市"), "530")
        self.assertIsNone(get_zhilian_city_code("不存在的城市"))

    def test_list_and_detail_fixture_are_platform_specific_and_convertible(self):
        item = parse_zhilian_list_html(
            (FIXTURES / "zhilian_search.html").read_text(encoding="utf-8"),
            city="北京",
            source_keyword="AI 产品",
        )[0]
        detail = parse_zhilian_detail_html(
            (FIXTURES / "zhilian_detail.html").read_text(encoding="utf-8"),
            source_job_id=item["source_job_id"],
            list_candidate=item,
        )

        self.assertEqual(item["source_job_id"], "zl-1001")
        self.assertEqual(item["title"], "AI 产品实习生")
        self.assertEqual(detail["jd"], "负责 AI 招聘产品的用户调研、需求分析和数据复盘。")
        candidate = ZhilianCollector._candidate_from_detail(detail, ZhilianCollector._candidate_from_list(item, "北京", "AI 产品"))
        self.assertEqual(candidate.storage_id, "zhilian:zl-1001")
        self.assertEqual(candidate.platform, "zhilian")

    def test_current_live_dom_fixture_ignores_normal_login_link_and_reads_fields(self):
        item = parse_zhilian_list_html(
            (FIXTURES / "zhilian_current_search.html").read_text(encoding="utf-8"),
            city="深圳",
            source_keyword="人力",
        )[0]
        detail = parse_zhilian_detail_html(
            (FIXTURES / "zhilian_current_detail.html").read_text(encoding="utf-8"),
            source_job_id=item["source_job_id"],
            list_candidate=item,
        )

        self.assertEqual(item["source_job_id"], "CC123J40800000001")
        self.assertEqual(item["city"], "深圳·南山·南山")
        self.assertEqual(detail["title"], "人力资源信息管理岗")
        self.assertEqual(detail["company"], "示例科技有限公司")
        self.assertEqual(detail["city"], "深圳·南山·南山")
        self.assertIn("HR 系统管理", detail["jd"])

    def test_list_card_without_href_builds_detail_url_from_platform_job_id(self):
        items = parse_zhilian_list_html(
            """
            <div class="positionlist__list">
              <div class="joblist-box__item" data-positionid="NOHREF-1">
                <span class="jobinfo__name">人力专员</span>
                <p class="jobinfo__salary">8千-1万</p>
                <span class="jobinfo__other-info-item">深圳·南山</span>
                <div class="companyinfo__name">示例公司</div>
              </div>
            </div>
            """,
            city="深圳",
            source_keyword="人力",
        )

        self.assertEqual(items[0]["source_job_id"], "NOHREF-1")
        self.assertEqual(items[0]["url"], "https://www.zhaopin.com/jobdetail/NOHREF-1.htm")

    def test_current_dom_selectors_cover_anchor_company_and_detail_jd(self):
        self.assertIn(".companyinfo__name", JS_EXTRACT_LIST)
        self.assertIn(".job-card__title-clamp", JS_EXTRACT_LIST)
        self.assertIn(".job-card__title-main", JS_EXTRACT_LIST)
        self.assertIn(".job-card__company-name", JS_EXTRACT_LIST)
        self.assertIn(".job-card__location", JS_EXTRACT_LIST)
        self.assertIn("div.job-card", JS_EXTRACT_LIST)
        self.assertIn(".describtion-card__detail-content", JS_EXTRACT_DETAIL)
        self.assertIn("descriptionCard", JS_EXTRACT_DETAIL)
        self.assertIn("describtion-card__detail-content", JD_CLASSES)

    def test_current_spa_job_card_classes_parse_without_detail_anchor(self):
        items = parse_zhilian_list_html(
            """
            <div class="job-list-panel">
              <article class="job-card" data-positionid="CC-SPA-001">
                <div class="job-card__title-main">
                  <div class="job-card__title-clamp"><span class="vue-clamp__text">新媒体运营（兼职）</span></div>
                </div>
                <div class="job-card__salary">4000-8000元</div>
                <div class="job-card__company-row"><span class="job-card__company-name">厦门搜益教育科技有限公司</span></div>
                <div class="job-card__location">东莞</div>
              </article>
            </div>
            """,
            city="东莞",
            source_keyword="运营",
        )

        self.assertEqual(items, [{
            "source_job_id": "CC-SPA-001",
            "title": "新媒体运营（兼职）",
            "company": "厦门搜益教育科技有限公司",
            "salary": "4000-8000元",
            "city": "东莞",
            "url": "https://www.zhaopin.com/jobdetail/CC-SPA-001.htm",
            "source_keyword": "运营",
        }])

    def test_current_detail_markup_parses_without_list_fallback(self):
        detail = parse_zhilian_detail_html(
            """
            <div class="summary-planes__title">人力专员</div>
            <div class="summary-planes__salary">8千-1万</div>
            <div class="summary-planes__info">深圳 南山 经验不限 大专</div>
            <div class="company-info__name">示例公司</div>
            <div class="address-info__content">深圳南山区</div>
            <div class="describtion-card__detail-content">负责招聘与员工关系管理。</div>
            """,
            source_job_id="CC123J40800000001",
        )

        self.assertEqual(detail["title"], "人力专员")
        self.assertEqual(detail["company"], "示例公司")
        self.assertEqual(detail["salary"], "8千-1万")
        self.assertEqual(detail["jd"], "负责招聘与员工关系管理。")

    def test_detail_with_readable_jd_ignores_generic_login_cta(self):
        detail = parse_zhilian_detail_html(
            """
            <header><button>立即登录</button><span>请登录后查看更多服务</span></header>
            <div class="summary-planes__title">AI 产品经理</div>
            <div class="company-info__name">示例科技</div>
            <div class="address-info__content">北京市朝阳区</div>
            <div class="describtion-card__detail-content">负责 AI 产品规划与用户研究。</div>
            """,
            source_job_id="zl-login-cta",
            list_candidate={"city": "北京", "url": "/jobdetail/zl-login-cta.htm"},
        )

        self.assertIn("AI 产品规划", detail["jd"])

    def test_detail_explicit_login_wall_still_blocks_even_with_stale_jd(self):
        with self.assertRaises(CollectionBlockedError) as error:
            parse_zhilian_detail_html(
                """
                <div class="login-dialog">登录失效，请先登录后继续</div>
                <div class="describtion-card__detail-content">这是页面上残留的旧职位描述。</div>
                """,
                source_job_id="zl-expired",
            )

        self.assertEqual(error.exception.code, "login_required")

    def test_live_detail_script_prefers_readable_jd_over_generic_login_cta(self):
        status_line = next(line for line in JS_EXTRACT_DETAIL.splitlines() if "status:" in line)
        self.assertLess(status_line.index("jdText ? 'ready'"), status_line.index("loginRequired ? 'login_required'"))
        self.assertIn("loginDialog", JS_EXTRACT_DETAIL)
        self.assertIn("loginPage", JS_EXTRACT_DETAIL)

    def test_source_job_id_ignores_detail_query_parameters(self):
        self.assertEqual(
            _source_job_id(
                "http://www.zhaopin.com/jobdetail/CC123J40800000001.htm?refcode=4019&data_identity=opaque"
            ),
            "CC123J40800000001",
        )

    def test_live_list_script_reads_vue_job_fields_when_dom_text_is_empty(self):
        self.assertIn('item.__vue__', JS_EXTRACT_LIST)
        self.assertIn('item.__vueParentComponent', JS_EXTRACT_LIST)
        self.assertIn('vueJob.number', JS_EXTRACT_LIST)
        self.assertIn('vueJob.positionURL', JS_EXTRACT_LIST)
        self.assertIn('vueJob.companyName', JS_EXTRACT_LIST)
        self.assertIn('vueJob.jobDescription', JS_EXTRACT_LIST)

    def test_candidate_accepts_complete_vue_backed_list_payload(self):
        candidate = ZhilianCollector._candidate_from_list(
            {
                'source_job_id': 'CC192921310J40894884209',
                'title': '350+京东上门家政保洁师',
                'company': '京东集团',
                'salary': '7000-13000元',
                'city': '东莞',
                'url': 'http://www.zhaopin.com/jobdetail/CC192921310J40894884209.htm',
                'jd': '负责上门家政服务',
            },
            '东莞',
            '工程师',
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.source_job_id, 'CC192921310J40894884209')
        self.assertEqual(candidate.title, '350+京东上门家政保洁师')
        self.assertEqual(candidate.company, '京东集团')
        self.assertEqual(candidate.url, 'http://www.zhaopin.com/jobdetail/CC192921310J40894884209.htm')

    def test_list_candidate_still_fails_closed_without_id_title_or_url(self):
        self.assertIsNone(
            ZhilianCollector._candidate_from_list(
                {'company': '京东集团'}, '东莞', '工程师'
            )
        )

    def test_list_candidate_can_defer_company_until_detail_page(self):
        candidate = ZhilianCollector._candidate_from_list(
            {
                "source_job_id": "zl-2",
                "title": "人力专员",
                "url": "https://www.zhaopin.com/jobdetail/zl-2.htm",
            },
            "深圳",
            "人力",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.company, "")

    def test_build_search_url_uses_current_city_search_page(self):
        url = ZhilianCollector.build_search_url(
            PlatformCollectionRequest("zhilian", ["人力"], ["深圳"], {"深圳": "765"}),
            "深圳",
            "人力",
            1,
        )
        self.assertEqual(url, "https://www.zhaopin.com/jobs/?pageMode=search&jl=765")

    def test_missing_detail_jd_is_a_parse_failure(self):
        with self.assertRaises(CollectionError) as error:
            parse_zhilian_detail_html(
                '<div class="jobinfo__name">岗位</div><div class="companyinfo__name">公司</div><div class="jobinfo__city">北京</div>',
                source_job_id="zl-1",
                list_candidate={"url": "/job/1.html"},
            )
        self.assertEqual(error.exception.code, "parse_failed")

    def test_selector_change_is_explicitly_reported(self):
        with self.assertRaises(CollectionError) as error:
            parse_zhilian_list_html("<html><body><div>页面结构已变化，但列表节点全部消失；这是一段足够长的诊断文本，用于确认选择器整体失效而不是正常的空结果。</div></body></html>")
        self.assertEqual(error.exception.code, "selector_changed")

    def test_explicit_login_wall_is_blocked_but_login_link_is_not(self):
        with self.assertRaises(CollectionBlockedError) as error:
            parse_zhilian_list_html(
                '<html><body><input placeholder="输入职位、公司等搜索"><div>请先登录后查看职位详情</div></body></html>'
            )
        self.assertIn("登录", str(error.exception))

        with self.assertRaises(CollectionBlockedError) as modern_error:
            parse_zhilian_list_html(
                '<html><body><input placeholder="搜索职位、公司"><p>登录查看更多相关职位</p><button>立即登录</button></body></html>'
            )
        self.assertEqual(modern_error.exception.code, "login_required")

    def test_collector_uses_shared_runtime_and_stops_at_target(self):
        responses = {
            "list": json.dumps({"items": [
                {"source_job_id": "zl-1", "title": "岗位一", "company": "公司一", "city": "北京"},
                {"source_job_id": "zl-2", "title": "岗位二", "company": "公司二", "city": "北京"},
            ]}),
            "detail": json.dumps({"source_job_id": "zl-1", "title": "岗位一", "company": "公司一", "city": "北京", "jd": "JD"}),
        }
        opened: list[str] = []

        def new_tab(url, **_):
            opened.append(url)
            return f"tab-{len(opened)}"

        browser = ZhilianBrowser(
            new_tab=new_tab,
            close_tab=lambda _target: True,
            evaluate=lambda _target, script: responses["detail" if "describtion__detail-content" in script else "list"],
            scroll=lambda *_args, **_kwargs: True,
            wait_for_load=lambda *_args, **_kwargs: True,
        )
        collected = []
        hooks = CollectorHooks(
            stop_event=Event(),
            on_list_candidate=lambda candidate: True,
            on_candidate=lambda candidate: collected.append(candidate) or len(collected) < 1,
            on_parse_failed=lambda reason: self.fail(reason),
            on_event=lambda **_kwargs: None,
        )
        result = ZhilianCollector(browser=browser).collect(
            PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=1),
            hooks,
        )

        self.assertEqual(result.reason_code, "callback_stopped")
        self.assertEqual(len(collected), 1)
        self.assertEqual(opened[1], "https://www.zhaopin.com/jobdetail/zl-1.htm")

    def test_collector_submits_keyword_through_shared_browser_input_actions(self):
        responses = {
            "list": json.dumps({"items": [
                {"source_job_id": "zl-1", "title": "岗位一", "company": "公司一", "city": "北京", "url": "/job/1.html"},
            ]}),
            "detail": json.dumps({"source_job_id": "zl-1", "title": "岗位一", "company": "公司一", "city": "北京", "jd": "JD"}),
        }
        actions: list[tuple[str, str]] = []

        def record(name):
            def action(_target, value, **_kwargs):
                actions.append((name, value))
                return True
            return action

        browser = ZhilianBrowser(
            new_tab=lambda _url, **_kwargs: "tab-1",
            close_tab=lambda _target: True,
            evaluate=lambda _target, script: responses["detail" if "describtion__detail-content" in script else "list"],
            scroll=lambda *_args, **_kwargs: True,
            wait_for_load=lambda *_args, **_kwargs: True,
            click_action=record("click"),
            type_text_action=record("type"),
            press_key_action=record("key"),
        )
        hooks = CollectorHooks(
            stop_event=Event(),
            on_list_candidate=lambda candidate: True,
            on_candidate=lambda candidate: False,
            on_parse_failed=lambda reason: self.fail(reason),
            on_event=lambda **_kwargs: None,
        )

        result = ZhilianCollector(browser=browser).collect(
            PlatformCollectionRequest("zhilian", ["人力"], ["北京"], {"北京": "530"}, max_pages=1),
            hooks,
        )

        self.assertEqual(result.reason_code, "callback_stopped")
        self.assertEqual(actions, [
            (
                "click",
                "input.query-sug__input",
            ),
            ("key", "SelectAll"),
            ("key", "Backspace"),
            ("type", "人力"),
        ])

    def test_search_input_falls_back_to_legacy_selector(self):
        attempted = []

        def click(_target, selector, **_kwargs):
            attempted.append(selector)
            return len(attempted) == 2

        browser = ZhilianBrowser(click_action=click)

        self.assertTrue(ZhilianCollector(browser=browser)._click_search_input("tab-1"))
        self.assertEqual(attempted[0], "input.query-sug__input")
        self.assertIn("input.search-wrapper__input", attempted)
        from bosshunter.collection.platforms.zhilian import ZHILIAN_SEARCH_INPUT_SELECTOR
        self.assertIn("input[placeholder=", ZHILIAN_SEARCH_INPUT_SELECTOR)

    def test_current_home_search_dom_is_supported_by_all_search_scripts(self):
        from bosshunter.collection.platforms.zhilian import (
            JS_CLICK_SEARCH_BUTTON,
            JS_FOCUS_SEARCH_INPUT,
            JS_PROBE_SEARCH_TAB,
            JS_SUBMIT_SEARCH,
        )

        for script in (JS_PROBE_SEARCH_TAB, JS_FOCUS_SEARCH_INPUT, JS_SUBMIT_SEARCH):
            self.assertIn("input.search-wrapper__input", script)
        self.assertIn("input.search-wrapper__input", JS_CLICK_SEARCH_BUTTON)
        self.assertIn("a.search-wrapper__button", JS_CLICK_SEARCH_BUTTON)
        self.assertIn("input.search-wrapper__input", JS_EXTRACT_LIST)

    def test_collector_reads_current_split_page_by_clicking_job_card(self):
        search_state_calls = 0

        def evaluate_current(_target, script):
            nonlocal search_state_calls
            if "item_count" in script:
                search_state_calls += 1
                if search_state_calls == 1:
                    return json.dumps({"url": "https://www.zhaopin.com/jobs?jl=530", "input": "", "signature": "old"})
                return json.dumps({
                    "url": "https://www.zhaopin.com/jobs?jl=530&pageMode=search&kw=AI运营",
                    "input": "AI运营",
                    "signature": "new",
                })
            if "submitted_by" in script:
                return json.dumps({"ok": True, "value": "AI运营", "submitted_by": "button"})
            if "card.click()" in script:
                return json.dumps({"ok": True})
            if "descriptionCard" in script:
                return json.dumps({
                    "status": "ready",
                    "title": "AI 产品运营",
                    "company": "示例科技",
                    "salary": "1-2万",
                    "city": "北京",
                    "jd": "负责 AI 产品运营、用户增长与数据复盘。",
                    "url": "https://www.zhaopin.com/jobdetail/CC123J40800000001.htm",
                })
            return json.dumps({"status": "ready", "items": [{"card_index": 0, "company": "示例科技", "city": "北京"}]})

        navigated = []
        browser = ZhilianBrowser(
            new_tab=lambda _url, **_kwargs: "tab-current",
            close_tab=lambda _target: True,
            evaluate=evaluate_current,
            scroll=lambda *_args, **_kwargs: True,
            wait_for_load=lambda *_args, **_kwargs: True,
            navigate_action=lambda _target, url: navigated.append(url) or True,
        )
        collected = []
        hooks = CollectorHooks(
            stop_event=None,
            on_list_candidate=lambda candidate: True,
            on_candidate=lambda candidate: collected.append(candidate) or False,
            on_parse_failed=lambda reason: self.fail(reason),
            on_event=lambda **_kwargs: None,
        )

        result = ZhilianCollector(browser=browser, sleep=lambda _seconds: None).collect(
            PlatformCollectionRequest("zhilian", ["AI运营"], ["北京"], {"北京": "530"}, max_pages=1),
            hooks,
        )

        self.assertEqual(result.reason_code, "callback_stopped")
        self.assertEqual(navigated, ["https://www.zhaopin.com/jobs/?pageMode=search&jl=530"])
        self.assertEqual(collected[0].storage_id, "zhilian:CC123J40800000001")
        self.assertIn("用户增长", collected[0].jd)

    def test_complete_list_payload_skips_changed_split_detail_panel(self):
        """A complete list item remains collectible when optional detail DOM changes."""
        evaluated_scripts = []

        def evaluate_current(_target, script):
            evaluated_scripts.append(script)
            if "item_count" in script:
                return json.dumps({
                    "url": "https://www.zhaopin.com/jobs?jl=779&pageMode=search&kw=Python",
                    "input": "Python",
                    "signature": "new",
                })
            if "submitted_by" in script:
                return json.dumps({"ok": True, "value": "Python", "submitted_by": "button"})
            if "descriptionCard" in script:
                self.fail("complete list payload must not read the changed detail panel")
            return json.dumps({
                "status": "ready",
                "items": [{
                    "card_index": 0,
                    "source_job_id": "CC821752090J40934301408",
                    "title": "Python开发工程师",
                    "company": "东莞佰和生物科技有限公司",
                    "salary": "8-12K",
                    "city": "东莞",
                    "jd": "负责 Python 服务开发和接口维护",
                    "url": "https://www.zhaopin.com/jobdetail/CC821752090J40934301408.htm",
                    "hr_name": "刘先生",
                }],
            })

        browser = ZhilianBrowser(
            new_tab=lambda _url, **_kwargs: self.fail("complete list payload must not open a detail tab"),
            close_tab=lambda _target: True,
            evaluate=evaluate_current,
            scroll=lambda *_args, **_kwargs: True,
            wait_for_load=lambda *_args, **_kwargs: True,
        )
        collected = []
        hooks = CollectorHooks(
            stop_event=None,
            on_list_candidate=lambda _candidate: True,
            on_candidate=lambda candidate: collected.append(candidate) or False,
            on_parse_failed=lambda reason: self.fail(reason),
            on_event=lambda **_kwargs: None,
        )

        result = ZhilianCollector(browser=browser, sleep=lambda _seconds: None).collect(
            PlatformCollectionRequest("zhilian", ["Python"], ["东莞"], {"东莞": "779"}, max_pages=1),
            hooks,
        )

        self.assertEqual(result.reason_code, "callback_stopped")
        self.assertEqual(len(collected), 1)
        self.assertEqual(collected[0].company, "东莞佰和生物科技有限公司")
        self.assertEqual(collected[0].hr_name, "刘先生")
        self.assertEqual(collected[0].jd, "负责 Python 服务开发和接口维护")
        self.assertFalse(any("descriptionCard" in script for script in evaluated_scripts))

    def test_reused_search_tab_accepts_already_applied_keyword_route(self):
        browser = ZhilianBrowser(
            evaluate=lambda _target, _script: json.dumps({
                "url": "https://www.zhaopin.com/jobs/?jl=779&pageMode=search&kw=%E5%B7%A5%E7%A8%8B%E5%B8%88",
                "input": "工程师",
                "signature": "same-result-signature",
                "item_count": 8,
            })
        )

        ZhilianCollector(browser=browser, sleep=lambda _seconds: None)._wait_for_search_results(
            "tab-1",
            "工程师",
            {"signature": "same-result-signature"},
            timeout=0.1,
        )

    def test_same_input_without_applied_route_is_not_accepted_as_search(self):
        browser = ZhilianBrowser(
            evaluate=lambda _target, _script: json.dumps({
                "url": "https://www.zhaopin.com/jobs/?jl=779&pageMode=search",
                "input": "工程师",
                "signature": "same-result-signature",
                "item_count": 8,
            })
        )

        with self.assertRaises(CollectionError) as raised:
            ZhilianCollector(browser=browser, sleep=lambda _seconds: None)._wait_for_search_results(
                "tab-1",
                "工程师",
                {"signature": "same-result-signature"},
                timeout=0.01,
            )
        self.assertEqual(raised.exception.code, "search_not_applied")

    def test_detail_reader_rechecks_a_transient_false_login_state(self):
        responses = iter([
            {"status": "login_required", "title": "AI 产品运营", "company": "示例科技", "jd": ""},
            {
                "status": "ready",
                "title": "AI 产品运营",
                "company": "示例科技",
                "city": "北京",
                "jd": "负责 AI 产品运营。",
                "url": "https://www.zhaopin.com/jobdetail/zl-retry.htm",
            },
        ])
        waits = []
        browser = ZhilianBrowser(
            evaluate=lambda _target, _script: json.dumps(next(responses)),
        )
        collector = ZhilianCollector(browser=browser, sleep=waits.append)

        detail = collector._read_detail_with_retry("tab-current", "北京")

        self.assertEqual(detail["status"], "ready")
        self.assertEqual(waits, [0.8])


class ZhilianEnhancedTests(TestCase):
    """智联采集器增强：时间窗口 / 过滤链 / config 集成。"""

    def _hooks(self):
        return CollectorHooks(
            stop_event=None,
            on_list_candidate=lambda _c: True,
            on_candidate=lambda _c: True,
            on_parse_failed=lambda _r: None,
            on_event=lambda **_: None,
        )

    def test_outside_send_window_skips_collection(self):
        collector = ZhilianCollector()
        with patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=False):
            result = collector.collect(
                PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=1),
                self._hooks(),
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.reason_code, "outside_window")

    def test_day_off_skips_collection(self):
        collector = ZhilianCollector()
        with (
            patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=True),
            patch("bosshunter.collection.platforms.zhilian.should_take_day_off", return_value=True),
        ):
            result = collector.collect(
                PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=1),
                self._hooks(),
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.reason_code, "day_off")

    def test_deal_breaker_filter(self):
        from bosshunter.collection.models import JobCandidate
        collector = ZhilianCollector(config={"profile": {"deal_breakers": ["外包"]}})
        c = JobCandidate(platform="zhilian", source_job_id="1", title="外包AI",
                         company="公司", city="北京", city_code="530")
        self.assertFalse(collector._passes_filters(c))

    def test_blocked_company_filter(self):
        from bosshunter.collection.models import JobCandidate
        collector = ZhilianCollector(config={"profile": {"blocked_companies": ["黑名单"]}})
        c = JobCandidate(platform="zhilian", source_job_id="1", title="AI工程师",
                         company="黑名单", city="北京", city_code="530")
        self.assertFalse(collector._passes_filters(c))

    def test_internship_filter(self):
        from bosshunter.collection.models import JobCandidate
        collector = ZhilianCollector(config={"profile": {"allow_internship": False}})
        c = JobCandidate(platform="zhilian", source_job_id="1", title="AI实习",
                         company="公司", city="北京", city_code="530")
        self.assertFalse(collector._passes_filters(c))

    def test_no_filter_passes(self):
        from bosshunter.collection.models import JobCandidate
        collector = ZhilianCollector()
        c = JobCandidate(platform="zhilian", source_job_id="1", title="AI工程师",
                         company="公司", city="北京", city_code="530")
        self.assertTrue(collector._passes_filters(c))


class ZhilianResumeCheckpointTests(TestCase):
    """智联断点续采：词级跳过 / 页级恢复 / checkpoint 记录 / 完成标记。"""

    def _hooks(self, collected=None, events=None):
        collected = collected if collected is not None else []
        events = events if events is not None else []
        return CollectorHooks(
            stop_event=None,
            on_list_candidate=lambda _c: True,
            on_candidate=lambda c: collected.append(c) or True,
            on_parse_failed=lambda _r: None,
            on_event=lambda **kw: events.append(kw),
        )

    def _browser_with_pages(self, pages_jobs):
        """pages_jobs: dict[int, list[dict]] — page number to list items.
        None means empty (no items)."""
        list_calls = {"n": 0}
        detail_payload = json.dumps({
            "source_job_id": "zl-1", "title": "AI", "company": "公司",
            "city": "北京", "jd": "JD 内容", "status": "ready",
        })

        def evaluate(_target, script):
            if "describtion__detail-content" in script:
                return detail_payload
            if "expectedCity" not in script:
                return json.dumps({"items": [], "status": "ready"})
            list_calls["n"] += 1
            page_num = list_calls["n"]
            jobs = pages_jobs.get(page_num)
            if jobs is None:
                return json.dumps({"items": [], "status": "empty"})
            return json.dumps({"items": jobs, "status": "ready"}, ensure_ascii=False)

        browser = ZhilianBrowser(
            new_tab=lambda _url, **_kw: "tab-1",
            close_tab=lambda _t: True,
            evaluate=evaluate,
            scroll=lambda *_a, **_kw: True,
            wait_for_load=lambda *_a, **_kw: True,
            click_action=lambda _t, _v, **_kw: True,
            type_text_action=lambda _t, _v, **_kw: True,
            press_key_action=lambda _t, _v, **_kw: True,
        )
        return browser

    def test_waits_for_transient_empty_spa_list_without_reloading(self):
        job = {"source_job_id": "zl-1", "title": "AI"}
        payloads = iter([
            {"items": [], "status": "empty"},
            {"items": [job], "status": "ready"},
        ])
        reads = []
        waits = []

        result = _wait_for_rendered_list(
            lambda: reads.append(True) or next(payloads),
            sleep=waits.append,
        )

        self.assertEqual(result["items"], [job])
        self.assertEqual(len(reads), 2)
        self.assertEqual(waits, [0.4])

    def test_empty_spa_list_wait_is_bounded(self):
        reads = []
        waits = []

        result = _wait_for_rendered_list(
            lambda: reads.append(True) or {"items": [], "status": "empty"},
            sleep=waits.append,
        )

        self.assertEqual(result, {"items": [], "status": "empty"})
        self.assertEqual(len(reads), 6)
        self.assertEqual(waits, [0.4] * 5)

    def _job(self, job_id="zl-1"):
        return {"source_job_id": job_id, "title": "AI", "company": "公司",
                "city": "北京", "url": f"/job/{job_id}.html"}

    def test_completed_combo_skipped_entirely(self):
        browser = self._browser_with_pages({1: [self._job()]})
        collected = []
        events = []
        collector = ZhilianCollector(
            browser=browser, safety_conn=object(),
            sleep=lambda _s: None, uniform=lambda _a, _b: 10.0,
        )
        with (
            patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=True),
            patch("bosshunter.collection.platforms.zhilian.should_take_day_off", return_value=False),
            patch("bosshunter.collection.platforms.zhilian.prune_collected_combos"),
            patch("bosshunter.collection.platforms.zhilian.prune_page_progress"),
            patch("bosshunter.collection.platforms.zhilian.get_collected_combos", return_value={("北京", "AI")}),
            patch("bosshunter.collection.platforms.zhilian.get_page_progress", return_value=0),
            patch("bosshunter.collection.platforms.zhilian.upsert_page_progress"),
            patch("bosshunter.collection.platforms.zhilian.mark_combo_collected"),
            patch("bosshunter.collection.platforms.zhilian.delete_page_progress"),
        ):
            result = collector.collect(
                PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=1),
                self._hooks(collected, events),
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(collected), 0)
        skip_events = [e for e in events if e.get("phase") == "completed_keyword"]
        self.assertTrue(any("断点续采" in str(e.get("message", "")) for e in skip_events))

    def test_pages_are_checkpointed_in_ascending_order(self):
        browser = self._browser_with_pages({1: [self._job()], 2: [self._job("zl-2")], 3: None})
        collected = []
        checkpoints = []
        collector = ZhilianCollector(
            browser=browser, safety_conn=object(),
            sleep=lambda _s: None, uniform=lambda _a, _b: 10.0,
        )
        with (
            patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=True),
            patch("bosshunter.collection.platforms.zhilian.should_take_day_off", return_value=False),
            patch("bosshunter.collection.platforms.zhilian.prune_collected_combos"),
            patch("bosshunter.collection.platforms.zhilian.prune_page_progress"),
            patch("bosshunter.collection.platforms.zhilian.get_collected_combos", return_value=set()),
            patch("bosshunter.collection.platforms.zhilian.get_page_progress", return_value=0),
            patch("bosshunter.collection.platforms.zhilian.upsert_page_progress",
                  side_effect=lambda _c, _s, _ci, _k, page: checkpoints.append(page)),
            patch("bosshunter.collection.platforms.zhilian.mark_combo_collected"),
            patch("bosshunter.collection.platforms.zhilian.delete_page_progress"),
        ):
            result = collector.collect(
                PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=3),
                self._hooks(collected),
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(checkpoints, [1, 2])

    def test_word_completion_marks_combo_and_clears_page_progress(self):
        browser = self._browser_with_pages({1: [self._job()], 2: None})
        collected = []
        collector = ZhilianCollector(
            browser=browser, safety_conn=object(),
            sleep=lambda _s: None, uniform=lambda _a, _b: 10.0,
        )
        with (
            patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=True),
            patch("bosshunter.collection.platforms.zhilian.should_take_day_off", return_value=False),
            patch("bosshunter.collection.platforms.zhilian.prune_collected_combos"),
            patch("bosshunter.collection.platforms.zhilian.prune_page_progress"),
            patch("bosshunter.collection.platforms.zhilian.get_collected_combos", return_value=set()),
            patch("bosshunter.collection.platforms.zhilian.get_page_progress", return_value=0),
            patch("bosshunter.collection.platforms.zhilian.upsert_page_progress"),
            patch("bosshunter.collection.platforms.zhilian.mark_combo_collected") as mark_complete,
            patch("bosshunter.collection.platforms.zhilian.delete_page_progress") as delete_progress,
        ):
            result = collector.collect(
                PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=2),
                self._hooks(collected),
            )
        self.assertEqual(result.status, "completed")
        mark_complete.assert_called_once()
        delete_progress.assert_called_once()

    def test_blocked_page_does_not_mark_combo(self):
        browser = ZhilianBrowser(
            new_tab=lambda _url, **_kw: "tab-1",
            close_tab=lambda _t: True,
            evaluate=lambda _t, _s: json.dumps({"items": [], "status": "blocked"}),
            scroll=lambda *_a, **_kw: True,
            wait_for_load=lambda *_a, **_kw: True,
            click_action=lambda _t, _v, **_kw: True,
            type_text_action=lambda _t, _v, **_kw: True,
            press_key_action=lambda _t, _v, **_kw: True,
        )
        collector = ZhilianCollector(
            browser=browser, safety_conn=object(),
            sleep=lambda _s: None, uniform=lambda _a, _b: 10.0,
        )
        with (
            patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=True),
            patch("bosshunter.collection.platforms.zhilian.should_take_day_off", return_value=False),
            patch("bosshunter.collection.platforms.zhilian.prune_collected_combos"),
            patch("bosshunter.collection.platforms.zhilian.prune_page_progress"),
            patch("bosshunter.collection.platforms.zhilian.get_collected_combos", return_value=set()),
            patch("bosshunter.collection.platforms.zhilian.get_page_progress", return_value=0),
            patch("bosshunter.collection.platforms.zhilian.upsert_page_progress"),
            patch("bosshunter.collection.platforms.zhilian.mark_combo_collected") as mark_complete,
            patch("bosshunter.collection.platforms.zhilian.delete_page_progress"),
        ):
            result = collector.collect(
                PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=3),
                self._hooks(),
            )
        self.assertEqual(result.status, "blocked")
        mark_complete.assert_not_called()

    def test_saved_page_exceeds_max_pages_skips_keyword(self):
        browser = self._browser_with_pages({1: [self._job()]})
        collected = []
        events = []
        collector = ZhilianCollector(
            browser=browser, safety_conn=object(),
            sleep=lambda _s: None, uniform=lambda _a, _b: 10.0,
        )
        with (
            patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=True),
            patch("bosshunter.collection.platforms.zhilian.should_take_day_off", return_value=False),
            patch("bosshunter.collection.platforms.zhilian.prune_collected_combos"),
            patch("bosshunter.collection.platforms.zhilian.prune_page_progress"),
            patch("bosshunter.collection.platforms.zhilian.get_collected_combos", return_value=set()),
            patch("bosshunter.collection.platforms.zhilian.get_page_progress", return_value=5),
            patch("bosshunter.collection.platforms.zhilian.upsert_page_progress"),
            patch("bosshunter.collection.platforms.zhilian.mark_combo_collected") as mark_complete,
            patch("bosshunter.collection.platforms.zhilian.delete_page_progress") as delete_progress,
        ):
            result = collector.collect(
                PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=3),
                self._hooks(collected, events),
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(collected), 0)
        mark_complete.assert_called_once()
        delete_progress.assert_called_once()
        skip_events = [e for e in events if e.get("phase") == "completed_keyword"]
        self.assertTrue(any("页级断点" in str(e.get("message", "")) for e in skip_events))

    def test_prune_called_on_collect_start(self):
        browser = self._browser_with_pages({1: [self._job()], 2: None})
        collector = ZhilianCollector(
            browser=browser, safety_conn=object(),
            sleep=lambda _s: None, uniform=lambda _a, _b: 10.0,
        )
        with (
            patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=True),
            patch("bosshunter.collection.platforms.zhilian.should_take_day_off", return_value=False),
            patch("bosshunter.collection.platforms.zhilian.prune_collected_combos") as prune_combos,
            patch("bosshunter.collection.platforms.zhilian.prune_page_progress") as prune_pages,
            patch("bosshunter.collection.platforms.zhilian.get_collected_combos", return_value=set()),
            patch("bosshunter.collection.platforms.zhilian.get_page_progress", return_value=0),
            patch("bosshunter.collection.platforms.zhilian.upsert_page_progress"),
            patch("bosshunter.collection.platforms.zhilian.mark_combo_collected"),
            patch("bosshunter.collection.platforms.zhilian.delete_page_progress"),
        ):
            collector.collect(
                PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=2),
                self._hooks(),
            )
        prune_combos.assert_called_once()
        prune_pages.assert_called_once()

    def test_resume_ttl_hours_from_config(self):
        collector = ZhilianCollector(
            config={"platforms": {"zhilian": {"search": {"resume_ttl_hours": 48}}}},
        )
        self.assertEqual(collector._resume_ttl_hours(), 48)

    def test_resume_ttl_hours_clamped_to_range(self):
        collector_low = ZhilianCollector(
            config={"platforms": {"zhilian": {"search": {"resume_ttl_hours": -5}}}},
        )
        self.assertEqual(collector_low._resume_ttl_hours(), 1)
        collector_high = ZhilianCollector(
            config={"platforms": {"zhilian": {"search": {"resume_ttl_hours": 9999}}}},
        )
        self.assertEqual(collector_high._resume_ttl_hours(), 720)

    def test_resume_ttl_hours_default_when_missing(self):
        collector = ZhilianCollector()
        self.assertEqual(collector._resume_ttl_hours(), 24)

    def test_resume_ttl_hours_invalid_falls_back_to_default(self):
        collector = ZhilianCollector(
            config={"platforms": {"zhilian": {"search": {"resume_ttl_hours": "invalid"}}}},
        )
        self.assertEqual(collector._resume_ttl_hours(), 24)

    def test_no_safety_conn_skips_resume_logic(self):
        browser = self._browser_with_pages({1: [self._job()], 2: None})
        collected = []
        collector = ZhilianCollector(
            browser=browser, safety_conn=None,
            sleep=lambda _s: None, uniform=lambda _a, _b: 10.0,
        )
        with (
            patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=True),
            patch("bosshunter.collection.platforms.zhilian.should_take_day_off", return_value=False),
            patch("bosshunter.collection.platforms.zhilian.prune_collected_combos") as prune_combos,
            patch("bosshunter.collection.platforms.zhilian.get_collected_combos") as get_combos,
            patch("bosshunter.collection.platforms.zhilian.get_page_progress") as get_progress,
            patch("bosshunter.collection.platforms.zhilian.upsert_page_progress") as upsert,
            patch("bosshunter.collection.platforms.zhilian.mark_combo_collected") as mark,
        ):
            result = collector.collect(
                PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=2),
                self._hooks(collected),
            )
        self.assertEqual(result.status, "completed")
        prune_combos.assert_not_called()
        get_combos.assert_not_called()
        get_progress.assert_not_called()
        upsert.assert_not_called()
        mark.assert_not_called()


def _api_body(results=None, num_total=0, code=200, api_code=200, message=""):
    """构造智联 API 响应 JSON body。"""
    return json.dumps({
        "code": code,
        "apiCode": api_code,
        "message": message,
        "data": {
            "results": results or [],
            "numTotal": num_total,
            "numFound": num_total,
            "taskId": "test-task",
        },
    }, ensure_ascii=False)


def _api_item(**overrides):
    """构造智联 API item。"""
    base = {
        "number": "CC123",
        "jobName": "AI 工程师",
        "companyName": "测试科技",
        "salary": "15-25K",
        "cityName": "北京",
        "jobDesc": "负责 AI 系统开发",
        "workingExp": "3-5年",
        "education": "本科",
        "url": "/jobdetail/CC123.htm",
    }
    base.update(overrides)
    return base


class ZhilianApiAnalyzeTests(TestCase):
    """_analyze_api_response 风控分级测试。"""

    def test_l0_normal_with_results(self):
        body = _api_body(results=[_api_item()], num_total=1)
        r = _analyze_api_response(200, "application/json", body)
        self.assertTrue(r["ok"])
        self.assertEqual(r["level"], 0)
        self.assertEqual(r["signal"], "ok")
        self.assertEqual(len(r["jobs"]), 1)
        self.assertEqual(r["total"], 1)

    def test_l0_no_results(self):
        body = _api_body(results=[], num_total=0)
        r = _analyze_api_response(200, "application/json", body)
        self.assertTrue(r["ok"])
        self.assertEqual(r["level"], 0)
        self.assertEqual(r["signal"], "no_results")
        self.assertEqual(r["jobs"], [])

    def test_l1_parse_error(self):
        r = _analyze_api_response(200, "application/json", "{invalid json")
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 1)
        self.assertEqual(r["signal"], "parse_error")

    def test_l2_empty_items_with_total(self):
        body = _api_body(results=[], num_total=50)
        r = _analyze_api_response(200, "application/json", body)
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 2)
        self.assertEqual(r["signal"], "empty_items")
        self.assertEqual(r["total"], 50)

    def test_l2_api_limited(self):
        body = _api_body(results=[], num_total=0, code=403, message="请求过于频繁")
        r = _analyze_api_response(200, "application/json", body)
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 2)
        self.assertEqual(r["signal"], "api_limited")

    def test_l3_http_error(self):
        r = _analyze_api_response(403, "text/plain", "Forbidden")
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 3)
        self.assertEqual(r["signal"], "http_error")

    def test_l3_non_json_html(self):
        r = _analyze_api_response(200, "text/html", "<html><body>Not JSON</body></html>")
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 3)
        self.assertEqual(r["signal"], "non_json")

    def test_l3_non_json_captcha_hint(self):
        r = _analyze_api_response(200, "text/html", "<html>请完成验证码</html>")
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 3)
        self.assertIn("验证", r["note"])

    def test_l3_non_json_login_hint(self):
        r = _analyze_api_response(200, "text/html", "<html>请先登录</html>")
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 3)
        self.assertIn("登录", r["note"])

    def test_l3_hard_risk_with_captcha(self):
        body = _api_body(results=[], num_total=0, code=403, message="请完成验证码")
        r = _analyze_api_response(200, "application/json", body)
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 3)
        self.assertEqual(r["signal"], "hard_risk")

    def test_l3_hard_risk_with_ban(self):
        body = _api_body(results=[], num_total=0, code=403, message="账号已被封禁")
        r = _analyze_api_response(200, "application/json", body)
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 3)
        self.assertEqual(r["signal"], "hard_risk")

    def test_empty_body(self):
        r = _analyze_api_response(200, "application/json", "")
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 3)
        self.assertEqual(r["signal"], "non_json")

    def test_results_not_list(self):
        body = json.dumps({"code": 200, "data": {"results": "not_a_list", "numTotal": 5}})
        r = _analyze_api_response(200, "application/json", body)
        self.assertFalse(r["ok"])
        self.assertEqual(r["level"], 2)
        self.assertEqual(r["signal"], "empty_items")

    def test_missing_data_block(self):
        body = json.dumps({"code": 200})
        r = _analyze_api_response(200, "application/json", body)
        self.assertTrue(r["ok"])
        self.assertEqual(r["signal"], "no_results")


class ZhilianApiRateLimiterTests(TestCase):
    """_ApiRateLimiter 速率限制器测试。"""

    def test_light_tier(self):
        limiter = _ApiRateLimiter(total_requests=30)
        self.assertEqual(limiter.per_min_limit, 30)
        self.assertEqual(limiter.gap_range, (2.0, 3.0))

    def test_medium_tier(self):
        limiter = _ApiRateLimiter(total_requests=100)
        self.assertEqual(limiter.per_min_limit, 20)
        self.assertEqual(limiter.gap_range, (3.0, 5.0))

    def test_heavy_tier(self):
        limiter = _ApiRateLimiter(total_requests=200)
        self.assertEqual(limiter.per_min_limit, 12)
        self.assertEqual(limiter.gap_range, (5.0, 8.0))

    def test_default_tier_no_arg(self):
        limiter = _ApiRateLimiter()
        self.assertEqual(limiter.per_min_limit, 30)

    def test_set_tier_updates_params(self):
        limiter = _ApiRateLimiter(total_requests=10)
        self.assertEqual(limiter.per_min_limit, 30)
        limiter.set_tier(200)
        self.assertEqual(limiter.per_min_limit, 12)

    def test_wait_before_request_returns_true_no_stop(self):
        limiter = _ApiRateLimiter(total_requests=10, no_burst=True)
        with patch("bosshunter.collection.platforms.zhilian._wait_or_stop", return_value=False):
            self.assertTrue(limiter.wait_before_request(None))


class ZhilianReasonCodeTests(TestCase):
    """_reason_code_for 映射测试。"""

    def test_parse_error_maps_to_selector_changed(self):
        self.assertEqual(_reason_code_for({"signal": "parse_error"}), "selector_changed")

    def test_other_signals_map_to_rate_limit(self):
        for signal in ("http_error", "non_json", "hard_risk", "api_limited", "empty_items", "ok"):
            self.assertEqual(_reason_code_for({"signal": signal}), "rate_limit")


class ZhilianItemToCandidateTests(TestCase):
    """_item_to_candidate 字段映射测试。"""

    def test_normal_item(self):
        cand = ZhilianCollector._item_to_candidate(_api_item(), "北京", "530", "AI")
        self.assertIsNotNone(cand)
        self.assertEqual(cand.platform, "zhilian")
        self.assertEqual(cand.source_job_id, "CC123")
        self.assertEqual(cand.title, "AI 工程师")
        self.assertEqual(cand.company, "测试科技")
        self.assertEqual(cand.salary, "15-25K")
        self.assertEqual(cand.city, "北京")
        self.assertEqual(cand.jd, "负责 AI 系统开发")
        self.assertEqual(cand.experience, "3-5年")
        self.assertEqual(cand.education, "本科")
        self.assertEqual(cand.source_keyword, "AI")

    def test_missing_job_id_returns_none(self):
        item = _api_item(number="")
        self.assertIsNone(ZhilianCollector._item_to_candidate(item, "北京", "530", "AI"))

    def test_missing_title_returns_none(self):
        item = _api_item(jobName="")
        self.assertIsNone(ZhilianCollector._item_to_candidate(item, "北京", "530", "AI"))

    def test_alternative_field_names(self):
        item = {
            "positionId": "P001",
            "positionName": "后端开发",
            "company": " alt公司",
            "salaryStr": "20-30K",
            "workCity": "上海",
            "positionDesc": "后端开发职责",
            "workYear": "5-10年",
            "degree": "硕士",
        }
        cand = ZhilianCollector._item_to_candidate(item, "上海", "020", "后端")
        self.assertIsNotNone(cand)
        self.assertEqual(cand.source_job_id, "P001")
        self.assertEqual(cand.title, "后端开发")
        self.assertEqual(cand.company, "alt公司")
        self.assertEqual(cand.salary, "20-30K")
        self.assertEqual(cand.city, "上海")
        self.assertEqual(cand.jd, "后端开发职责")

    def test_url_fallback_from_job_id(self):
        item = _api_item()
        del item["url"]
        cand = ZhilianCollector._item_to_candidate(item, "北京", "530", "AI")
        self.assertIsNotNone(cand)
        self.assertIn("CC123", cand.url)

    def test_non_dict_returns_none(self):
        self.assertIsNone(ZhilianCollector._item_to_candidate("not_a_dict", "北京", "530", "AI"))
        self.assertIsNone(ZhilianCollector._item_to_candidate(None, "北京", "530", "AI"))


class ZhilianApiFetchEnabledTests(TestCase):
    """_api_fetch_enabled 配置开关测试。"""

    def test_default_disabled(self):
        self.assertFalse(ZhilianCollector()._api_fetch_enabled())

    def test_enabled_via_config(self):
        collector = ZhilianCollector(
            config={"platforms": {"zhilian": {"search": {"api_fetch": True}}}},
        )
        self.assertTrue(collector._api_fetch_enabled())

    def test_disabled_explicitly(self):
        collector = ZhilianCollector(
            config={"platforms": {"zhilian": {"search": {"api_fetch": False}}}},
        )
        self.assertFalse(collector._api_fetch_enabled())

    def test_invalid_config_disabled(self):
        collector = ZhilianCollector(config={"platforms": "not_a_dict"})
        self.assertFalse(collector._api_fetch_enabled())


class ZhilianCollectApiTests(TestCase):
    """_collect_api 集成测试（mock browser）。"""

    def setUp(self):
        self._patches = [
            patch("bosshunter.collection.platforms.zhilian.SendWindowChecker.is_active", return_value=True),
            patch("bosshunter.collection.platforms.zhilian.should_take_day_off", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _hooks(self, collected):
        return CollectorHooks(
            stop_event=None,
            on_event=lambda **kw: None,
            on_list_candidate=lambda c: True,
            on_candidate=lambda c: collected.append(c) or True,
            on_parse_failed=lambda msg: None,
        )

    def test_api_host_ignores_im_tab_and_uses_public_search_tab(self):
        browser = ZhilianBrowser(
            get_page_targets=lambda: [
                {"targetId": "im-tab", "url": "https://i.zhaopin.com/im?sessionId=abc"},
                {"targetId": "jobs-tab", "url": "https://www.zhaopin.com/jobs/?jl=779"},
            ],
            evaluate=lambda target, _script, **_kwargs: (
                json.dumps({"http_status": 200, "content_type": "application/json", "body": "{}"})
                if target == "jobs-tab" else None
            ),
            new_tab=lambda *_args, **_kwargs: "new-tab",
        )
        request = PlatformCollectionRequest("zhilian", ["工程师"], ["东莞"], {"东莞": "779"}, max_pages=1)

        target, owned = ZhilianCollector(browser=browser, sleep=lambda _s: None)._ensure_host_tab(request)

        self.assertEqual(target, "jobs-tab")
        self.assertFalse(owned)

    def test_city_search_tab_requires_exact_jl_code(self):
        browser = ZhilianBrowser(
            get_page_targets=lambda: [
                {"targetId": "guangzhou", "url": "https://www.zhaopin.com/jobs/?pageMode=search&jl=763"},
                {"targetId": "dongguan", "url": "https://www.zhaopin.com/jobs/?pageMode=search&jl=779&kw=工程师"},
                {"targetId": "im-tab", "url": "https://i.zhaopin.com/im"},
            ],
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)

        self.assertEqual(collector._find_city_search_tab("779"), "dongguan")
        self.assertIsNone(collector._find_city_search_tab("530"))

    def test_city_search_tab_accepts_normalized_runtime_target_id_shapes(self):
        browser = ZhilianBrowser(
            get_page_targets=lambda: [
                {"target_id": "dongguan", "url": "https://www.zhaopin.com/jobs/?jl=779"},
                {"id": "other", "url": "https://www.zhaopin.com/jobs/?jl=763"},
            ],
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)

        self.assertEqual(collector._find_city_search_tab("779"), "dongguan")

    def test_city_search_tab_skips_stale_target_and_selects_live_target(self):
        browser = ZhilianBrowser(
            get_page_targets=lambda: [
                {"targetId": "stale", "url": "https://www.zhaopin.com/jobs/?jl=779"},
                {"targetId": "live", "url": "https://www.zhaopin.com/jobs/?jl=779"},
            ],
            evaluate=lambda target, _script, **_kwargs: (
                None if target == "stale" else '{"ok":true,"url":"https://www.zhaopin.com/jobs/?jl=779"}'
            ),
            navigate_action=lambda *_args: True,
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)

        self.assertEqual(collector._find_city_search_tab("779"), "live")

    def test_city_search_tab_returns_none_when_all_matching_targets_are_stale(self):
        browser = ZhilianBrowser(
            get_page_targets=lambda: [
                {"targetId": "stale", "url": "https://www.zhaopin.com/jobs/?jl=779"},
            ],
            evaluate=lambda *_args, **_kwargs: None,
            navigate_action=lambda *_args: True,
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)

        self.assertIsNone(collector._find_city_search_tab("779"))

    def test_wait_for_search_page_reports_live_runtime_load_failure(self):
        browser = ZhilianBrowser(
            navigate_action=lambda _target, _url: True,
            wait_for_load=lambda *_args, **_kwargs: False,
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)

        self.assertFalse(collector._wait_for_search_page("stalled"))

    def test_wait_for_search_page_keeps_legacy_offline_fake_compatible(self):
        browser = ZhilianBrowser(
            wait_for_load=lambda *_args, **_kwargs: False,
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)

        self.assertTrue(collector._wait_for_search_page("offline"))

    def test_dom_tab_reuses_exact_city_and_only_new_tab_is_owned(self):
        created = []
        browser = ZhilianBrowser(
            get_page_targets=lambda: [
                {"targetId": "dongguan", "url": "https://www.zhaopin.com/jobs/?jl=779"},
            ],
            new_tab=lambda url, **_kwargs: created.append(url) or "new-tab",
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)
        request = PlatformCollectionRequest("zhilian", ["AI"], ["东莞"], {"东莞": "779"}, max_pages=1)

        reused, reused_owned = collector._ensure_dom_tab(request, "东莞", collector.build_search_url(request, "东莞", "AI", 1))
        self.assertEqual((reused, reused_owned), ("dongguan", False))
        self.assertEqual(created, [])

        browser.get_page_targets = lambda: []
        opened, opened_owned = collector._ensure_dom_tab(request, "东莞", collector.build_search_url(request, "东莞", "AI", 1))
        self.assertEqual((opened, opened_owned), ("new-tab", True))
        self.assertEqual(created, ["https://www.zhaopin.com/jobs/?pageMode=search&jl=779"])

    def test_dom_tab_skips_target_with_dead_runtime_context(self):
        created = []
        browser = ZhilianBrowser(
            get_page_targets=lambda: [
                {"targetId": "stale", "url": "https://www.zhaopin.com/jobs/?jl=779"},
            ],
            evaluate=lambda *_args, **_kwargs: None,
            navigate_action=lambda _target, _url: True,
            new_tab=lambda url, **_kwargs: created.append(url) or "fresh",
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)
        request = PlatformCollectionRequest("zhilian", ["AI"], ["city"], {"city": "779"}, max_pages=1)

        target, owned = collector._ensure_dom_tab(request, "city", collector.build_search_url(request, "city", "AI", 1))

        self.assertEqual((target, owned), ("fresh", True))
        self.assertEqual(created, ["about:blank"])

    def test_dom_tab_reuses_target_with_live_runtime_context(self):
        browser = ZhilianBrowser(
            get_page_targets=lambda: [
                {"targetId": "live", "url": "https://www.zhaopin.com/jobs/?jl=779"},
            ],
            evaluate=lambda *_args, **_kwargs: json.dumps({"ok": True, "url": "https://www.zhaopin.com/jobs/?jl=779"}),
            navigate_action=lambda _target, _url: True,
            new_tab=lambda *_args, **_kwargs: self.fail("a live search target should be reused"),
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)
        request = PlatformCollectionRequest("zhilian", ["AI"], ["city"], {"city": "779"}, max_pages=1)

        target, owned = collector._ensure_dom_tab(request, "city", collector.build_search_url(request, "city", "AI", 1))

        self.assertEqual((target, owned), ("live", False))

    def test_no_host_tab_returns_none(self):
        browser = ZhilianBrowser(
            get_page_targets=lambda: [],
            new_tab=lambda *a, **kw: None,
            close_tab=lambda t: True,
            evaluate=lambda *a, **kw: None,
            scroll=lambda *a, **kw: True,
            wait_for_load=lambda *a, **kw: True,
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)
        request = PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=1)
        result = collector._collect_api(request, self._hooks([]), set())
        self.assertIsNone(result)

    def test_api_success_collects_jobs(self):
        api_response = json.dumps({
            "http_status": 200,
            "content_type": "application/json",
            "body": _api_body(results=[_api_item()], num_total=1),
        })
        browser = ZhilianBrowser(
            get_page_targets=lambda: [],
            new_tab=lambda *a, **kw: "host-1",
            close_tab=lambda t: True,
            evaluate=lambda *a, **kw: api_response,
            scroll=lambda *a, **kw: True,
            wait_for_load=lambda *a, **kw: True,
        )
        collected = []
        collector = ZhilianCollector(
            browser=browser, sleep=lambda _s: None,
            config={"profile": {"deal_breakers": [], "blocked_companies": []}},
        )
        request = PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=1)
        result = collector._collect_api(request, self._hooks(collected), set())
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(collected), 1)
        self.assertEqual(collected[0].source_job_id, "CC123")

    def test_api_non_json_falls_back_to_dom(self):
        api_response = json.dumps({
            "http_status": 200,
            "content_type": "text/html",
            "body": "<html>Not JSON</html>",
        })
        browser = ZhilianBrowser(
            get_page_targets=lambda: [],
            new_tab=lambda *a, **kw: "host-1",
            close_tab=lambda t: True,
            evaluate=lambda *a, **kw: api_response,
            scroll=lambda *a, **kw: True,
            wait_for_load=lambda *a, **kw: True,
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)
        request = PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=1)
        result = collector._collect_api(request, self._hooks([]), set())
        self.assertIsNone(result)

    def test_api_hard_risk_raises_blocked(self):
        api_response = json.dumps({
            "http_status": 200,
            "content_type": "application/json",
            "body": _api_body(results=[], num_total=0, code=403, message="请完成验证码"),
        })
        browser = ZhilianBrowser(
            get_page_targets=lambda: [],
            new_tab=lambda *a, **kw: "host-1",
            close_tab=lambda t: True,
            evaluate=lambda *a, **kw: api_response,
            scroll=lambda *a, **kw: True,
            wait_for_load=lambda *a, **kw: True,
        )
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)
        request = PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=1)
        with self.assertRaises(CollectionBlockedError) as ctx:
            collector._collect_api(request, self._hooks([]), set())
        self.assertEqual(ctx.exception.code, "rate_limit")

    def test_api_skips_collected_combos(self):
        api_response = json.dumps({
            "http_status": 200,
            "content_type": "application/json",
            "body": _api_body(results=[_api_item()], num_total=1),
        })
        browser = ZhilianBrowser(
            get_page_targets=lambda: [],
            new_tab=lambda *a, **kw: "host-1",
            close_tab=lambda t: True,
            evaluate=lambda *a, **kw: api_response,
            scroll=lambda *a, **kw: True,
            wait_for_load=lambda *a, **kw: True,
        )
        collected = []
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)
        request = PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=1)
        result = collector._collect_api(
            request, self._hooks(collected), {("北京", "AI")},
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(collected), 0)

    def test_api_empty_page_ends_keyword(self):
        api_response = json.dumps({
            "http_status": 200,
            "content_type": "application/json",
            "body": _api_body(results=[], num_total=0),
        })
        browser = ZhilianBrowser(
            get_page_targets=lambda: [],
            new_tab=lambda *a, **kw: "host-1",
            close_tab=lambda t: True,
            evaluate=lambda *a, **kw: api_response,
            scroll=lambda *a, **kw: True,
            wait_for_load=lambda *a, **kw: True,
        )
        collected = []
        collector = ZhilianCollector(browser=browser, sleep=lambda _s: None)
        request = PlatformCollectionRequest("zhilian", ["AI"], ["北京"], {"北京": "530"}, max_pages=3)
        result = collector._collect_api(request, self._hooks(collected), set())
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(collected), 0)
