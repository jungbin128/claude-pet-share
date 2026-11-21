# 변경 이력

버전은 `주 버전.기능 버전.수정 버전` 형식입니다. 한 번의 배포에 여러 기능이 들어가도 기능 버전은 한 번 올립니다. 기능 추가와 수정이 함께 있으면 기능 버전을 올리고 수정 버전은 0으로 시작합니다. 자세한 규칙은 [버전 관리](docs/VERSIONING.md)를 따릅니다.

## [2.2.21] - 2026-11-21

- 멍모닝 이름표 글꼴을 검증된 픽셀 비트맵으로 복귀

## [2.2.19] - 2026-11-21

- 멍모닝 호버 포즈의 이름표 중복 노출 수정

## [2.2.18] - 2026-11-21

- 멍모닝 이름표에서 축소로 빠진 한글 획 복구

## [2.2.17] - 2026-11-21

- 멍모닝 이름표 글자를 미세 축소하고 획 대비 강화

## [2.2.16] - 2026-11-21

- 업데이트 확인을 별도 제한 시간 프로세스에서 실행해 무응답 상태 방지

## [2.2.15] - 2026-11-21

- 업데이트 확인 리디렉션과 네트워크 대기 상한

## [2.2.14] - 2026-11-21

- 수동 새 버전 확인과 자동 다운로드 동작 분리

## [2.2.13] - 2026-11-21

- 2.2.6 업데이트 검증기와 패키지 경로 호환

## [2.2.12] - 2026-11-21

- 멍모닝 이름표 글자 크기 미세 축소

## [2.2.11] - 2026-11-21

- 업데이트 연결 경로 보강 및 실패 단계 표시

## [2.2.10] - 2026-11-21

- 멍모닝 이름표 획 굵기 미세 조정

## [2.2.9] - 2026-11-21

- 멍모닝 이름표 픽셀 획 굵기 균일화

## [2.2.8] - 2026-11-21

- 멍모닝 명찰 글자 획을 균일한 픽셀 폰트로 교체

## [2.2.7] - 2026-11-21

- 멍모닝 이름표에 Neo둥근모 Pro와 큰 글자 적용

## [2.2.6] - 2026-11-21

- 업데이트 대기 버전 표시와 멍모닝 이름표 위치 보정

## [2.2.5] - 2026-11-21

- 멍모닝 이름표 글자 정렬 보정

## [2.2.4] - 2026-11-21

- 멍모닝 명찰 글자를 픽셀풍으로 정리하고 획을 미세 조정

## [2.2.3] - 2026-11-21

- 멍모닝 명찰 글자를 얇게 조정

## [2.2.2] - 2026-11-21

- 멍모닝 명찰 글자 가독성 개선

## [2.2.1] - 2026-11-21

- 멍모닝 이름표 글자 가독성과 업데이트 버전 안내 개선

## [2.2.0] - 2026-11-21

- 멍모닝을 네 번째 선택 펫으로 추가하고 앉기·간식·대기·호버·완료 액션과 완료 시 빛나는 명찰 테두리를 구성

## [2.1.1] - 2026-11-20

- 무이치로 스킨을 2배 픽셀 밀도로 개선하고 표시 크기를 유지하며, 뒷머리의 땋은 듯한 가닥을 자연스럽게 정리

## [2.1.0] - 2026-11-20

- Add Tokito Muichiro (menu name `무이치로`) as the third selectable pet, with seated idle/wait poses and standing work, hover and completion reactions.
- Rename the Charmander (파이리) skin ID, folder and preview assets; existing saved skin selections migrate automatically.
- Include only the two official skins in public packages; unrelated user skins and all personal runtime data remain excluded.
- Validation: 25 skin, distribution and version tests passed. Full Linux discovery ran 140 tests with 6 Windows API setup errors and 1 Windows OCR skip; GUI, tray, IME and monitor behavior require Windows validation.

## [2.0.2] - 2026-11-20

- 업데이트 화면 상단에 현재 설치 버전을 고정 표시하고 업데이트 상태를 별도 행으로 분리

## [2.0.1] - 2026-11-20

- 단일 펫 표시의 이동 경로에 누락된 화면 경계 제한 추가. 모든 화면 표시 여부와 무관하게 본체 전체와 하단 막대가 작업 영역 안에 유지.
- 고정 좌표 여백 대신 선택한 스킨·크기·DPI의 실제 좌우·상하 크기로 경계 계산. 다중 화면도 같은 계산을 사용하고 정수 반올림에 의한 경계 누출 방지.
- 화면 가장자리에서 크기·스킨을 바꾸거나 저장 위치가 잘못된 경우에도 표시 전 위치 보정·기억. 다른 연결 모니터로의 이동은 유지.
- 검증: 회귀 테스트 174개 통과. 단일/다중 화면, 음수 좌표, 작업표시줄 영역, 100/150/200% 배율과 실제 로봇·Charmander 크기별 경계 확인.

## [2.0.0] - 2026-11-20

- 별도 공개 공유 저장소와 Claude Code용 붙여넣기 설치 요청문. 개인 자료가 제외된 소스 ZIP·설치 사전 점검·사용자 전용 Python 환경.
- 기존 Claude 설정 백업·펫 훅만 병합·중복 등록 방지·로그인 트레이와 수동 실행 파일 구성.
- GitHub 정식 Release 확인(시작 후·5분 간격), 수동 확인·적용, 선택형 자동 업데이트.
- GitHub 자산 SHA-256·파일별 체크섬·ZIP 경로와 크기 검증. 개발 체크아웃과 개인 설정·스킨 보호.
- 입력·드래그·메뉴 조작 중 적용 연기, 외부 도우미에서 코드 교체·시작 확인·실패 시 복구.
- 공개 소스와 파일·통신 설명, 재현 가능한 빌드·게시 스크립트. 이전 개인용 메뉴·트레이 개선도 포함.
- 검증: 자동 회귀 테스트 163개 통과. 별도 한글·공백 경로에 실제 가상환경 설치, 정상 GUI 시작·업데이트, 의도적인 새 버전 시작 실패 후 이전 버전 복구 확인.

## [1.3.0] - 2026-11-20 (개발 단계, 별도 미배포)

- 선명한 주황색 픽셀 로봇·전구 트레이 아이콘과 더블클릭으로 펫 켜기.
- 펫·트레이 메뉴를 용도별로 묶고 빨간 **펫 숨기기**와 **자동 실행** 설정을 분리. 크기 조절을 하위 메뉴로 정리.
- 자동 실행 설정에 켜기·끄기 및 **Windows 로그인 시 / Claude 실행 시** 선택 추가. 트레이에서 Claude 실행을 감지하며 Code 새 세션도 지원. 기존 중지·완전 종료 버튼 제거.
- 수동으로 펫을 켜도 자동 실행 토글은 유지. 숨기면 화면·OCR·작업 감시는 종료하고 트레이만 유지.
- 트레이의 **Claude 펫 삭제**: 확인 후 전용 로컬 설치 폴더·개인 설정·스킨·상태·로그·펫 훅·로그인 시작 항목 제거. 다른 Claude 설정·원본 대화·Python은 보존.
- 삭제 중 재실행 방지, 전용 경로 검증, 임시 도우미 자기 삭제, 읽기 전용 파일 제거, 다른 훅 보존 및 설정 동시 수정 감지.
- 작업표시줄·트레이·달력·음량 등 Windows 셸 창이 펫·말풍선·메뉴보다 앞에 유지되도록 조정.
- Explorer 재시작 시 아이콘 재등록, 중복 실행 방지, 종료 중 다시 켜기 대기 처리.
- 트레이 메뉴의 실제 Tk 입력 영역을 화면 크기와 일치시켜 클릭 처리 개선.
- 검증: 회귀 테스트 137개 통과. 실제 트레이 메뉴에서 시점 선택·독립 토글·숨김 유지·새 Code 세션 실행을 확인하고 사용자 설정 복원. 제거는 임시 설치 폴더에서 검증.

## [1.2.0] - 2026-11-19

### 추가

- 다중 모니터 전체 표시, 같은 상대 위치로 동기화 이동, 해제한 화면에만 펫 남기기.
- 말풍선별 우클릭 메뉴: 크기·폰트 크기·전체 투명도·자동 감지 개별 설정과 저장.
- 크기·폰트 비율을 그룹 제목에 실시간 표시하고, 가로 슬라이더로 투명도 조절.
- 화면별 독립 자동 투명화: Windows OCR로 뒤쪽 글자를 감지하고 호버·글자 소멸 시 사용자 설정으로 복귀.
- 대화별 미확인 완료 상태를 재실행 후에도 보존하고, 확인 전까지 모든 펫의 완료 리액션 반복.
- 펫 변경 목록의 얼굴 아이콘과 정돈된 우클릭 메뉴, 세밀한 펫 크기 조절.
- `VERSION`, 변경 이력, 버전 관리 규칙과 검사·증가 도구.

### 수정 및 개선

- 사용량 패널의 화면 경계 회피, 드래그 중 말풍선 재배치 및 원래 자리 자동 복귀.
- 입력창 미리보기 자동 닫힘과 완료 리액션 중 펫 클릭으로 확인 처리.
- 제공 스킨 표시 이름을 파이리로 변경하고, 도트 불꽃 그라데이션·얇고 일정한 외곽선 정리.
- 다중 화면의 감지·호버·투명도 분리, 빈 영역·가장자리 글자의 OCR 오탐 감소.
- 우클릭 메뉴의 최상위 표시 순서와 OCR/창 열기 Win32 콜백 간섭 수정.
- 말풍선·회전 표시·그림자·화면별 렌더 프로필 캐시, 변경 없는 OCR 재사용 및 중복 인식 제거.
- 감지 도우미 수명·파이프 정리, 작업 상태 갱신과 예외 복구 보완.
- 펫 회귀 테스트 77개와 버전 관리 테스트 8개, 총 85개 통과. 실제 듀얼 모니터·OCR·입력창·대화별 메뉴 검증.

## [1.1.0] - 2026-11-19

기존 커밋 `67c861d`에 사후 버전 태그를 부여했습니다.

### 추가

- Charmander(파이리) 애니메이션 스킨: 64×72 투명 PNG 16장과 장면별 프레임 재생.
- 스킨 로더와 작업·대기·호버·완료 장면 선택, 눈 깜빡임·대체 프레임 지원.
- 모든 펫 공통 시그니처 불빛, 움직이는 화염 고리 효과.
- 스킨 제작·인계 문서, 미리보기와 기본 회귀 테스트.

## [1.0.0] - 2026-11-19

최초 등록 커밋 `2fc8881`에 사후 버전 태그를 부여했습니다. 저장소의 공개 범위는 기존의 비공개 설정을 유지합니다.

### 최초 버전

- Windows 바탕화면 위에 항상 표시되는 Claude 픽셀 로봇 펫.
- Claude Code 훅과 채팅·코워크 상태 감시, 대화별 진행 말풍선.
- 대화창 열기, 메시지 입력·전송과 한국어 IME, 자동 확장 입력창.
- 사용량·리셋 시각 표시와 동기화, 메뉴·크기 조절·위치 기억.
- 설치·시작프로그램 등록 안내와 개발 문서.

[1.2.0]: https://github.com/jungbin128/claude-pet/compare/1.1.0...1.2.0
[1.1.0]: https://github.com/jungbin128/claude-pet/compare/1.0.0...1.1.0
[1.0.0]: https://github.com/jungbin128/claude-pet/tree/1.0.0
[1.3.0]: https://github.com/jungbin128/claude-pet/compare/1.2.0...1.3.0
[2.0.0]: https://github.com/jungbin128/claude-pet/compare/1.3.0...2.0.0
[2.0.1]: https://github.com/jungbin128/claude-pet/compare/2.0.0...2.0.1
[2.0.2]: https://github.com/jungbin128/claude-pet/compare/2.0.1...2.0.2
[2.1.0]: https://github.com/jungbin128/claude-pet/compare/2.0.2...2.1.0
[2.1.1]: https://github.com/jungbin128/claude-pet/compare/2.1.0...2.1.1
[2.2.0]: https://github.com/jungbin128/claude-pet/compare/2.1.1...2.2.0
[2.2.1]: https://github.com/jungbin128/claude-pet/compare/2.2.0...2.2.1
[2.2.2]: https://github.com/jungbin128/claude-pet/compare/2.2.1...2.2.2
[2.2.3]: https://github.com/jungbin128/claude-pet/compare/2.2.2...2.2.3
[2.2.4]: https://github.com/jungbin128/claude-pet/compare/2.2.3...2.2.4
[2.2.5]: https://github.com/jungbin128/claude-pet/compare/2.2.4...2.2.5
[2.2.6]: https://github.com/jungbin128/claude-pet/compare/2.2.5...2.2.6
[2.2.7]: https://github.com/jungbin128/claude-pet/compare/2.2.6...2.2.7
[2.2.8]: https://github.com/jungbin128/claude-pet/compare/2.2.7...2.2.8
[2.2.9]: https://github.com/jungbin128/claude-pet/compare/2.2.8...2.2.9
[2.2.10]: https://github.com/jungbin128/claude-pet/compare/2.2.9...2.2.10
[2.2.11]: https://github.com/jungbin128/claude-pet/compare/2.2.10...2.2.11
[2.2.12]: https://github.com/jungbin128/claude-pet/compare/2.2.11...2.2.12
[2.2.13]: https://github.com/jungbin128/claude-pet/compare/2.2.12...2.2.13
[2.2.14]: https://github.com/jungbin128/claude-pet/compare/2.2.13...2.2.14
[2.2.15]: https://github.com/jungbin128/claude-pet/compare/2.2.14...2.2.15
[2.2.16]: https://github.com/jungbin128/claude-pet/compare/2.2.15...2.2.16
[2.2.17]: https://github.com/jungbin128/claude-pet/compare/2.2.16...2.2.17
[2.2.18]: https://github.com/jungbin128/claude-pet/compare/2.2.17...2.2.18
[2.2.19]: https://github.com/jungbin128/claude-pet/compare/2.2.18...2.2.19
[2.2.21]: https://github.com/jungbin128/claude-pet/compare/2.2.19...2.2.21
