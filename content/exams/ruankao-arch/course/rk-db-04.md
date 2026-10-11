关系代数和 SQL 每年 1～2 题，常见问法：结果有几列几行、和某个表达式等价的 SQL、哪个查询效率最高。

## 一、关系代数运算

| 运算 | 符号 | 结果 |
|---|---|---|
| 并、差、交 | ∪ − ∩ | 要求两个关系**结构相同**（同元、同域） |
| 笛卡尔积 | × | 列数相加，**行数相乘** |
| 选择 | σ | 选行（按条件） |
| 投影 | π | 选列 |
| θ 连接 | ⋈ | 笛卡尔积后按条件选行 |
| **自然连接** | ⋈ | 在同名属性上做等值连接，并**去掉重复的同名列** |
| 除 | ÷ | “包含所有”类查询 |

:::example 自然连接的列数
R(A, B, C, D)、S(C, D, E)，R ⋈ S 有几列？
--- 同名属性
C、D 两列同名，自然连接在 C、D 上等值，并去掉 S 中重复的 C、D
--- 答案
4 + 3 − 2 = **5 列**（A, B, C, D, E）
:::

:::tip 查询效率
先**选择**（减少行）、先**投影**（减少列），再做连接，效率最高。题目给几个等价表达式问“效率最高的是哪个”时，选**最早做选择**的那个。
:::

## 二、SQL 语句结构

```
SELECT [DISTINCT] 列 / 聚集函数
FROM 表
WHERE 行条件
GROUP BY 分组列
HAVING 组条件（可以用聚集函数）
ORDER BY 排序列 [ASC|DESC]
```

:::key WHERE 和 HAVING
WHERE 在分组**前**筛选行，**不能用聚集函数**；HAVING 在分组**后**筛选组，可以用 COUNT、SUM、AVG 等。
:::

## 三、其他常考语句

- **视图**：CREATE VIEW … AS SELECT …；WITH CHECK OPTION 保证通过视图修改的数据满足视图条件；
- **授权**：GRANT 权限 ON 对象 TO 用户 [WITH GRANT OPTION]（允许他再授权给别人）；REVOKE 收回；
- **完整性**：PRIMARY KEY、FOREIGN KEY … REFERENCES、UNIQUE、NOT NULL、CHECK；
- **索引**：加快查询，但减慢插入和修改。

:::quiz 随堂测验
R 有 3 列 4 行，S 有 2 列 5 行，R × S 的结果是：
A. 5 列 20 行
B. 6 列 9 行
C. 5 列 9 行
D. 6 列 20 行
答案：A
解析：笛卡尔积列数相加 3 + 2，行数相乘 4 × 5。
---
查询“平均成绩大于 80 的班级”，平均成绩的条件应写在：
A. WHERE 中
B. HAVING 中
C. ORDER BY 中
D. SELECT 中
答案：B
---
允许被授权用户再把权限授给别人，应加上：
A. WITH CHECK OPTION
B. WITH GRANT OPTION
C. CASCADE
D. DISTINCT
答案：B
:::

:::cards 记忆卡
笛卡尔积的列数和行数 :: 列数相加，行数相乘
自然连接 :: 在同名属性上等值连接，并去掉重复列
提高查询效率的原则 :: 尽早做选择和投影，再连接
WHERE 和 HAVING 的区别 :: WHERE 分组前筛行、不能用聚集函数；HAVING 分组后筛组
WITH GRANT OPTION :: 被授权者可以把权限再授给别人
WITH CHECK OPTION :: 通过视图修改的数据必须满足视图条件
:::

:::practice 信息系统与数据库 | 关系代数与 SQL | 10 | all
:::
