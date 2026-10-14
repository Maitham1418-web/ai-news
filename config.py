"""مصادر البوت وإعداداته — عدّل هنا لإضافة مصدر أو حساب."""

# (الاسم، الرابط، النوع) — النوع "lab" = مدونة رسمية لشركة كبيرة، تُفحص في التنبيهات الفورية
FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml", "lab"),
    ("Anthropic", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml", "lab"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "lab"),
    ("Google AI", "https://blog.google/technology/ai/rss/", "lab"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml", "news"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "news"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "news"),
    ("r/LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day", "community"),
]

# Hacker News: قصص الذكاء الاصطناعي اللي تجاوزت هذا العدد من النقاط
HN_QUERY = "AI LLM GPT Claude Gemini OpenAI Anthropic"  # أي كلمة منها تكفي
HN_MIN_POINTS = 100

# حسابات X يركّز عليها البحث (Gemini يبحث عن منشوراتها عبر جوجل)
X_ACCOUNTS = [
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "xai", "AIatMeta", "MistralAI",
    "sama", "DarioAmodei", "demishassabis", "karpathy", "simonw", "emollick",
    "_akhaliq", "rowancheung", "swyx", "AndrewYNg", "DrJimFan", "SDAIA_SA",
]

SECTIONS = [
    "🚀 إطلاقات الموديلات والمنتجات",
    "🛠️ أدوات وطرق عملية",
    "🇸🇦 السعودية والخليج",
    "💰 تمويل وأبحاث",
]

# موديلات Gemini بالترتيب — لو واحد مزحوم ينتقل للي بعده
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.8-flash", "gemini-flash-latest",
                 "gemini-3.5-flash-lite"]

# رابط صفحة الويب اللي فيها التفاصيل (GitHub Pages)
PAGE_URL = "https://maitham1418-web.github.io/ai-news/"

# مستودعات GitHub الأعلى نجمة اليوم (صفحة Trending)
GITHUB_MAX_REPOS = 5
# وصفك — Gemini يستخدمه يشرح «وش فايدته لك لو ثبّته»
READER_PROFILE = ("مطوّر سعودي يبني منصات SaaS بـNext.js وSupabase، وبوتات تيليقرام، "
                  "وأتمتة بـGemini وClaude Code، ومحتوى فيديو بالذكاء الاصطناعي، ويشتغل على ويندوز")

DIGEST_MAX_ITEMS = 15
ALERTS_PER_DAY = 2
ALERT_WINDOW_HOURS = 3.5
TZ_OFFSET_HOURS = 3  # الرياض
