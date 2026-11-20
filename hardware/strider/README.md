# Stackchan Strider × CoreMatrix + FS90R の改造部品

[Stackchan Strider](https://github.com/Yeq6X/stackchan-strider) (Yeq6X さん、MIT) を、CoreMatrix + 18350×2 ベース + FEETECH FS90R で歩かせるための置き換え部品です。
脚・側板・デッキ・歯車・ピニオン・シャフト・クランク・クリップは原作の `print/stl/` をそのまま使い、`yoke_x1.stl` と `socket_frame_x1.stl` の代わりに下の 3 つを印刷します。

| ファイル | 役割 | 造形の向き |
|---|---|---|
| `horn_hub_x1.stl` | ソケット枠の代わり。上面の溝に FS90R の一文字ホーン (27.5×7) が入る | 上面 (溝) を下 |
| `cm_yoke_x1.stl` | ヨークの代わり。天板に FS90R を軸下向きに付属ネジ 2 本で吊る | 天板を下 |
| `cm_cradle_x1.stl` | 天板の前にスナップで留める受け台。CoreMatrix + 18350×2 ベースを顔を前にして立てる | 背板を下 |

- FS90R の耳穴ピッチは図面から 27.7mm と推定 (`SV_EAR_PITCH`)。実測と違えば直して作り直す
- 作り直し: 原作リポジトリの `walker/` にこの `cm_variant.py` を置いて `python walker/cm_variant.py` (原作の `design.py` を使う)
- 歩行 1 周で干渉なしを確認済み。ファームとアプリは本リポジトリの「歩行モード」(README) を参照

ライセンス: `cm_variant.py` と STL は Stackchan Strider の派生物なので、原作の MIT ライセンス (`LICENSE-stackchan-strider`、Copyright (c) 2026 Yeq6X) に従います。
