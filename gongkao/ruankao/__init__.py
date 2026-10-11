"""软考（先做高级 · 系统架构设计师）：把资料文件夹和开源题库整理成这门考试自己的题库、案例、论文、资料库。

整理结果都在 <数据目录>/exams/ruankao-arch/library/（见 exams.library_dir）：
- catalog.json   资料目录（每个文件的分类、年份、页数、有没有文字层）
- questions.db   综合知识选择题（真题 kind=paper、模拟题 kind=mock），表结构和公考的题库一样（qdb.py）
- cases.json     案例分析（真题、模拟题：说明材料、问题、分值、参考答案）
- essays.json    论文（历年论题、写作要点）
- docs.db        资料库文档（教材、讲义、笔记、范文，和公考资料库同一套整理流程，见 docs.py）
- videos.json    视频课（按章节归位）
- github/        从开源仓库下载的 Markdown 原文（CC BY-SA 4.0，标注来源）
原始资料只读不改。整理在后台任务里跑（library.jobs），后台线程没有请求，所以这里的函数都显式用 EXAM_ID。
"""

EXAM_ID = "ruankao-arch"


def lib_dir():
    from .. import exams

    return exams.library_dir(EXAM_ID)
