# Resource and dependency registry — SIB-TWO-PHASE-001 v1.2

| Task | Repository | AND dependencies | Priority | Resource locks |
|---|---|---|---|---|
| [SE-00](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/70) · Reconcile stacked baselines and authorize the Stable slice | builder | owner gate | P0 | stable/baseline |
| [SE-01](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/71) · Typed geometry authoring contract and shared render projection | builder | SE-00 | P0 | shared/ir; shared/compiler |
| [SE-02](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/72) · Volatile project actor, revisions and fenced write ownership | builder | SE-01 | P0 | stable/project-actor |
| [SE-03](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/73) · Authenticated remote Streamable HTTP MCP adapter | builder | SE-02 | P0 | stable/mcp; stable/auth-resource |
| [SE-04](https://github.com/KaisAbiyyi/sibambo-editor/issues/15) · MCP Extension onboarding, pairing and agent management | editor | SE-00 | P0 | stable/editor-onboarding; stable/auth-ui |
| [SE-05](https://github.com/KaisAbiyyi/sibambo-editor/issues/16) · Live draft WebSocket synchronization and lifecycle | editor | SE-03, SE-04 | P0 | stable/editor-sync |
| [SE-06](https://github.com/KaisAbiyyi/sibambo-editor/issues/17) · Render every acknowledged construction operation live | editor | SE-01, SE-05 | P0 | stable/editor-render |
| [SE-07](https://github.com/KaisAbiyyi/sibambo-editor/issues/18) · Explicit Save, frozen revision compile and original Editor reopen | editor | SE-06 | P0 | stable/save; shared/compiler |
| [SE-08](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/74) · Reconnect, actor recovery and multi-agent error semantics | builder | SE-02, SE-05, SE-07 | P1 | stable/project-actor; stable/recovery |
| [SE-09](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/75) · Cross-application security and bounded remote execution | builder | SE-03, SE-04, SE-05, SE-07 | P1 | stable/auth-resource; stable/security |
| [SE-10](https://github.com/KaisAbiyyi/sibambo-editor/issues/19) · Measured live rendering performance and onboarding usability | editor | SE-06, SE-08, SE-09 | P1 | stable/editor-performance; stable/ux-evidence |
| [SE-11](https://github.com/KaisAbiyyi/sibambo-editor/issues/20) · Real remote AI construction → live owner view → Save → reopen gate | editor | SE-07, SE-08, SE-09, SE-10 | P0 | stable/product-acceptance |
| [XB-00](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/76) · EXPERIMENTAL charter, future repository split and evaluation protocol | builder | owner gate | P2 | experimental/charter |
| [XB-01](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/77) · Exact-location map and evidence provenance experiment | builder | XB-00 | P2 | experimental/site |
| [XB-02](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/78) · Room-program onboarding and constraint interpretation | builder | XB-00 | P2 | experimental/room-program |
| [XB-03](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/79) · Client interview and desired-feeling research | builder | XB-00 | P2 | experimental/client-interview |
| [XB-04](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/80) · BYOK provider abstraction, credential safety and 27B Colab benchmark | builder | XB-00 | P2 | experimental/providers |
| [XB-05](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/81) · Native internal agent state machine and research synthesis | builder | XB-01, XB-02, XB-03, XB-04 | P2 | experimental/orchestrator |
| [XB-06](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/82) · Zoning and floor-plan algorithm comparison experiment | builder | XB-05 | P2 | experimental/spatial-planning |
| [XB-07](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/83) · Verified floor plan → Module IR → 3D/BOMC geometry | builder | XB-06, SE-01 | P2 | experimental/geometry-lowering |
| [XB-08](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/84) · Independent evaluation, environmental constraints and uncertainty | builder | XB-07 | P2 | experimental/evaluation |
| [XB-09](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/85) · Separate application split and three-stage onboarding prototype | builder | XB-01, XB-02, XB-03, XB-04, XB-08 | P2 | experimental/app-split |
| [XB-10](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/86) · Human feedback, localized revision and valid BOMC export | builder | XB-09 | P2 | experimental/feedback |
| [XB-11](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/87) · EXPERIMENTAL end-to-end pilot and provider go/no-go | builder | XB-10 | P2 | experimental/pilot |

## Publication resources

- notionMaster: https://app.notion.com/p/412c4a6aaf7381f79521c8c88e738381?pvs=204
- notionStable: https://app.notion.com/p/412c4a6aaf7381c5b063dc52002c89b9?pvs=204
- notionExperimental: https://app.notion.com/p/412c4a6aaf738120b069f2d7a9944f60?pvs=204
- notionADRs: https://app.notion.com/p/412c4a6aaf73818eadebd5ec456263f4?pvs=204
- notionGapAudit: https://app.notion.com/p/412c4a6aaf73815d8c86ce5d508a82a7?pvs=204
- notionExperimentalArchitecture: https://app.notion.com/p/412c4a6aaf73812e8e22fefc8d88d7df?pvs=204
- builderDraftPR: https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/88
- editorDraftPR: https://github.com/KaisAbiyyi/sibambo-editor/pull/21
- notionMasterV10: https://app.notion.com/p/412c4a6aaf7381adb3d6fd449e5c092e?pvs=204
- notionADRsV10: https://app.notion.com/p/412c4a6aaf738184ab96fa6335ba4429?pvs=204
- notionMasterV11: https://app.notion.com/p/412c4a6aaf7381219f69d83de8989878?pvs=204
- notionADRsV11: https://app.notion.com/p/412c4a6aaf7381bd833cff378b078a0f?pvs=204

## Task source-of-truth mapping

| Task | Notion | GitHub |
|---|---|---|
| SE-00 | https://app.notion.com/p/412c4a6aaf73817a95c4f924aeb464ab?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/70 |
| SE-01 | https://app.notion.com/p/412c4a6aaf738116964dc411de6377b0?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/71 |
| SE-02 | https://app.notion.com/p/412c4a6aaf73815db620eb541ab93435?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/72 |
| SE-03 | https://app.notion.com/p/412c4a6aaf7381049e91cd47e4924c37?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/73 |
| SE-04 | https://app.notion.com/p/412c4a6aaf73813e9ae3e4172ec00e55?pvs=204 | https://github.com/KaisAbiyyi/sibambo-editor/issues/15 |
| SE-05 | https://app.notion.com/p/412c4a6aaf7381e29bd5d6be758b2303?pvs=204 | https://github.com/KaisAbiyyi/sibambo-editor/issues/16 |
| SE-06 | https://app.notion.com/p/412c4a6aaf738141b140f7f4f4750290?pvs=204 | https://github.com/KaisAbiyyi/sibambo-editor/issues/17 |
| SE-07 | https://app.notion.com/p/412c4a6aaf73817897a4c6751980037a?pvs=204 | https://github.com/KaisAbiyyi/sibambo-editor/issues/18 |
| SE-08 | https://app.notion.com/p/412c4a6aaf738147ac4dfe112b3f7523?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/74 |
| SE-09 | https://app.notion.com/p/412c4a6aaf7381ea8d73eb2e09de33ea?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/75 |
| SE-10 | https://app.notion.com/p/412c4a6aaf73812c8805eeb230180589?pvs=204 | https://github.com/KaisAbiyyi/sibambo-editor/issues/19 |
| SE-11 | https://app.notion.com/p/412c4a6aaf73810885c3cfe999051754?pvs=204 | https://github.com/KaisAbiyyi/sibambo-editor/issues/20 |
| XB-00 | https://app.notion.com/p/412c4a6aaf7381e39599f0e898f751f6?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/76 |
| XB-01 | https://app.notion.com/p/412c4a6aaf7381fca0dad8c04661ffa6?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/77 |
| XB-02 | https://app.notion.com/p/412c4a6aaf7381169331f7daa2480932?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/78 |
| XB-03 | https://app.notion.com/p/412c4a6aaf73811aa82fee4b328daf02?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/79 |
| XB-04 | https://app.notion.com/p/412c4a6aaf7381d1864fdb8ba81750e0?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/80 |
| XB-05 | https://app.notion.com/p/412c4a6aaf738189ad16cc1bd6f7b8a1?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/81 |
| XB-06 | https://app.notion.com/p/412c4a6aaf738191a799cec5d517abb4?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/82 |
| XB-07 | https://app.notion.com/p/412c4a6aaf73819dac80fb8a7e4705d5?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/83 |
| XB-08 | https://app.notion.com/p/412c4a6aaf738163a7e9e6029e8a7f06?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/84 |
| XB-09 | https://app.notion.com/p/412c4a6aaf73812696bedb0e1892424e?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/85 |
| XB-10 | https://app.notion.com/p/412c4a6aaf738168b5b5da251a0dfa61?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/86 |
| XB-11 | https://app.notion.com/p/412c4a6aaf73814d8ea8f55f69de1363?pvs=204 | https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/87 |
