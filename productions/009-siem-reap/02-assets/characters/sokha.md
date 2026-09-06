# 速卡

- slug: sokha
- asset_id: CHAR_SOKHA_V1
- type: character
- binds_to: sokha
- what_it_locks: 身份（干衣底图）
- 22岁柬埔寨女大学生，水文与环境工程。识水、冷静、被绑也不乱。穿越后仍穿着现代勘测服，不换古装。

## 生产锁定（剧本「或」必须二选一）

发型锁 **低马尾、短黑发**（剧本写「短黑发或低马尾」）。全剧所有速卡图跟这一头，禁止下一张改成齐耳短发或披发。

## 锁定卡

| key | value | source |
|---|---|---|
| gender | 女 | script |
| age | 22 | script |
| nationality | 柬埔寨 | script |
| occupation | 水文与环境工程大学生 | script |
| hair | 短黑发，低马尾 | script（二选一已锁） |
| glasses | | inferred_empty |
| beard | | inferred_empty |
| skin | | inferred_empty |
| face_shape | | inferred_empty |
| height | | inferred_empty |
| body | | inferred_empty |
| costume | 现代野外勘测服，开场干燥 | script |
| costume_color | | inferred_empty |
| jewelry | | inferred_empty |
| temperament | 冷静 | script |
| expression | 平静 | 岗位默认 |
| pose | 正面或三视图站立，双手自然下垂 | 岗位默认 |

## 出图

- 文件：`02-assets/characters/sokha/master.jpg` 然后从 master 改 `face.jpg`
- 先 master，再 face。face 禁止另开新脸。
- 湿衣是另一张资产 `sokha-wet`，从本 master 改，不要新脸。
- 提示词只写长什么样，不写蹲槽、坠落、被绑。
