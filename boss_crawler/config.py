# -*- coding: utf-8 -*-
"""
config.py —— 全局配置
======================
只想改"搜什么、搜哪些城市"的话，改 DEFAULT_KEYWORDS 和 DEFAULT_CITIES 就够了。

城市编码来源：BOSS 公开接口 /wapi/zpCommon/data/city.json（2026-11-26 实测，3260 个城市）。
想加城市：在上面那个接口里搜城市名，取对应 code（9 位数字）。
"""

SEARCH_URL = "https://www.zhipin.com/web/geek/jobs?city={city}&query={keyword}"
DETAIL_URL = "https://www.zhipin.com/job_detail/{job_id}.html"
CHAT_URL = "https://www.zhipin.com/web/geek/chat"
LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"

# ---------------------------------------------------------------------------
# 城市名 -> BOSS 城市编码（city 参数，9 位）
# ---------------------------------------------------------------------------
CITY_CODES = {
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "武汉": "101200100",
    "南京": "101190100",
    "西安": "101110100",
    "苏州": "101190400",
    "长沙": "101250100",
    "郑州": "101180100",
    "重庆": "101040100",
    "天津": "101030100",
    "合肥": "101220100",
    "厦门": "101230200",
    "济南": "101120100",
    "青岛": "101120200",
    "宁波": "101210400",
    "佛山": "101280800",
    "东莞": "101281600",
    "昆明": "101290100",
    "南昌": "101240100",
    "石家庄": "101090100",
    "福州": "101230100",
}

# ---------------------------------------------------------------------------
# 默认搜索关键词 / 城市
# 一个关键词一页返回 15 条（BOSS 网页版固定），totalCount 通常 300 条上限
# ---------------------------------------------------------------------------
DEFAULT_KEYWORDS = ["Python", "Java", "前端", "数据分析", "测试", "算法"]

DEFAULT_CITIES = ["北京", "上海", "深圳", "杭州", "广州", "成都", "武汉", "南京"]

PER_PAGE = 15

# 采集节流：两次导航之间的最小/最大间隔（秒）。BOSS 风控严格，别调太小。
MIN_DELAY = 10.0
MAX_DELAY = 16.0

# 单个关键词最多翻几页（搜索接口 totalCount 上限 300，15 条/页即 20 页）
MAX_PAGES = 20

# 输出位置（相对于本文件夹）
OUTPUT_XLSX = "output/BOSS直聘岗位数据.xlsx"
OUTPUT_CSV = "output/BOSS直聘岗位数据.csv"
RAW_JSONL = "raw/岗位原始数据.jsonl"
CHAT_JSONL = "raw/沟通过列表.jsonl"
LOG_FILE = "运行日志.log"
BROWSER_PROFILE = "browser_data"
DEFAULT_PORT = 9222


class Settings:
    """一次采集任务的参数，由 main.py 根据命令行生成。"""

    def __init__(self, keywords=None, cities=None, max_jobs=300, pages=1,
                 min_delay=MIN_DELAY, max_delay=MAX_DELAY, port=DEFAULT_PORT,
                 profile=None, show=False, keep_open=False):
        self.keywords = keywords or list(DEFAULT_KEYWORDS)
        self.cities = cities or list(DEFAULT_CITIES)
        self.max_jobs = int(max_jobs)
        self.pages = max(1, int(pages))
        self.min_delay = float(min_delay)
        self.max_delay = float(max_delay)
        self.port = int(port)
        self.profile = profile
        self.show = bool(show)
        self.keep_open = bool(keep_open)

    def __repr__(self):
        return ("Settings(keywords=%s, cities=%s, max_jobs=%d, pages=%d)"
                % (self.keywords, self.cities, self.max_jobs, self.pages))
