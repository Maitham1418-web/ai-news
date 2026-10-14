# بوت أخبار الذكاء الاصطناعي 📰

يرسل لك على الإيميل:
- **ملخص يومي الساعة ٨ الصبح بتوقيت الرياض.** فيه أهم ١٠ إلى ١٥ خبر مقسّمة على أقسام، وفي أوله فقرة «وش يهمك اليوم».
- **تنبيه فوري** لما تطلق شركة كبيرة موديل أو منتج جديد. يفحص كل ٣ ساعات، وما يرسل أكثر من تنبيهين في اليوم.

## المصادر (كلها مجانية)
- **X:** يبحث Gemini في جوجل عن منشورات حسابات الذكاء الاصطناعي اللي في `config.py`، وعن الترندات.
- **RSS:** مدونات OpenAI وAnthropic وGoogle DeepMind وGoogle AI وHugging Face، وموقعي TechCrunch وThe Verge، وr/LocalLLaMA.
- **Hacker News:** القصص اللي تجاوزت ١٠٠ نقطة.

## الأسرار المطلوبة (Settings ← Secrets and variables ← Actions)
| السر | من وين |
|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey ← Create API key |
| `GMAIL_USER` | إيميل Gmail اللي يرسل منه البوت |
| `GMAIL_APP_PASSWORD` | https://myaccount.google.com/apppasswords. لازم يكون التحقق بخطوتين مفعّل. اكتب الـ١٦ حرف بدون مسافات |
| `TO_EMAIL` | اختياري. إذا ما حطيته، يرسل لنفس `GMAIL_USER` |

إعداد اختياري (Variables): `GEMINI_MODEL` لتغيير الموديل. الافتراضي `gemini-2.5-flash`.

## التشغيل اليدوي
تبويب **Actions** ← **AI News Digest** ← **Run workflow** ← اختر `daily` أو `alert`.

وعلى جهازك، للتجربة بدون إرسال (تنحفظ النتيجة في `out/`):
```bash
DRY_RUN=1 GEMINI_API_KEY=... python digest.py daily
```

## ملاحظات
- البوت يحفظ في `state/seen.json` الأخبار اللي أرسلها، عشان ما تتكرر عليك. ويرفع الملف تلقائيًا بعد كل تشغيل.
- لإضافة مصدر أو حساب X، عدّل `config.py`.
- للتوسّع لاحقًا: تقدر تضيف twitterapi.io لتغطية أوسع من X (حوالي ١ إلى ٣ دولار في الشهر).
