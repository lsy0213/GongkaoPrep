专业英语的完形填空不需要读懂每一个词，用对方法，5 题能对 3～4 题。

## 一、题目的样子

一段 150～250 词的英文短文，挖掉 5 个空，每空 4 个选项（通常是同一词性的专业名词或形容词）。主题往往就是本章学过的内容：架构风格、质量属性、微服务、架构评估等。

## 二、做题步骤

:::flow 四步法
看首句 :: 首句通常点出主题，例如 “Architecture evaluation is…”，确定讨论的是哪个知识点
找关键词 :: 空格前后的词往往是固定搭配，比如 “… coupling and high …” → cohesion
用中文知识推 :: 把句子大意翻成中文，结合学过的知识判断，例如 “ATAM focuses on … between quality attributes” → trade-offs
排除法 :: 词性不对、意思明显无关的先排除；剩两个时选和全文主题一致的
:::

## 三、常见的“送分”搭配

| 句子片段 | 答案 |
|---|---|
| loose coupling and high ___ | cohesion |
| quality attributes such as performance, security and ___ | availability / modifiability 等 |
| sensitivity points and ___ points | tradeoff |
| the ___ layer is responsible for user interaction | presentation |
| a ___ is a computational element, a connector is … | component |
| services communicate through lightweight ___ such as HTTP | protocols / mechanisms |
| a ___ is an independently deployable service | microservice |

:::example 真题风格示范
Software architecture is the ___(1)___ structure of a system, which comprises software ___(2)___, the externally visible properties of those elements, and the ___(3)___ among them.
--- 分析
第一句是软件架构的定义（Bass 的定义）：架构是系统的结构，由软件元素、元素的外部可见属性、元素之间的关系组成
--- 答案
(1) high-level / fundamental；(2) **elements**（或 components）；(3) **relationships**
:::

## 四、备考建议

- 每天 10 张英文闪卡（上一课的记忆卡）；
- 把历年真题的 5 道英语题全做一遍，不会的词记到笔记本；
- 考场上英语题放在综合知识的**最后做**，不要在前面卡太久。

:::quiz 随堂测验
“Microservices emphasize loose coupling and high ___.” 最合适的是：
A. complexity
B. cohesion
C. latency
D. redundancy
答案：B
---
“ATAM helps identify risks, sensitivity points and ___ points.” 最合适的是：
A. tradeoff
B. entry
C. access
D. failure
答案：A
:::

:::cards 记忆卡
专业英语在综合知识中的位置 :: 最后 5 题（第 71～75 题）
完形填空第一步 :: 看首句确定主题
架构定义的三要素（英文） :: elements、externally visible properties、relationships
loose coupling and high ___ :: cohesion
sensitivity points and ___ points :: tradeoff
presentation layer :: 表现层
:::

:::practice 专业英语 | 全部 | 10 | 真题
:::
