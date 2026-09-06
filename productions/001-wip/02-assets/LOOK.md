# 画风与一致性锁

Gate B 起，所有图、所有镜头只许从本页的主图改，不许对同一主体再开一张全新生成。

## 媒介

仿真人电影静帧。35mm，浅景深，细胶片颗粒，皮肤有毛孔。暖湄公金，不是冷白皮，不是韩系磨皮。

## 人

成年高棉面孔：橄榄到古铜，颧骨开阔，下颌偏圆，鼻梁中等，眼睛偏圆，乌黑直发。服饰是 sampot、sbai、金项圈与臂环，吴哥宫廷味道。

## 光

主光从画面左侧来，黄昏暖金，柔辅光。水下场景改成同一方向的绿金琉璃光，色温变，方向不变。

## 主图清单（只此一次 image_gen）

| slug | 文件 | 以后怎么用 |
|---|---|---|
| preah-thong | `characters/preah-thong/master.jpg` + `face.jpg` | 他的所有镜头 |
| neang-neak | `characters/neang-neak/master.jpg` + `face.jpg` | 她的所有镜头；sbai、鸡蛋花、肩鳞以此为准 |
| naga-king | `characters/naga-king/master.jpg` + `face.jpg` | 龙王两次露面 |
| island-shore-dusk | `scenes/island-shore-dusk/master.jpg` | 场 1；偏俯视，平视潮线要另改一版再塞人 |
| naga-corridor | `scenes/naga-corridor/master.jpg` | 场 2 |
| new-land | `scenes/new-land/master.jpg` | 场 3 |
| sbai | 锁在娜娘主图上，不单独另生一条 | 入水只让它发光展开 |

## 以后每张图

用 `image_edit`，主图当参考。提示词必须复述：同一张脸、同一套衣服、同一条披肩、同一道光。只写这一镜要改的那一件事。
