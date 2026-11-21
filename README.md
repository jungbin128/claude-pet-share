# Claude Pet · Windows

Claude가 작업하는 동안 다른 창을 보고 있어도 진행·완료를 알려주는 픽셀 펫입니다. Anthropic 공식 앱이 아닌 개인 제작 도구입니다.

## 가장 쉬운 설정 방법

**[Claude Code에 붙여 넣을 요청문](CLAUDE_INSTALL.md)**을 복사해 사용하세요. 실행 권한이 있는 Claude Code가 공개 소스를 확인하고 설정합니다. 일반 웹 채팅만으로는 PC에 설치할 수 없습니다.

[최신 소스 ZIP 받기](https://github.com/jungbin128/claude-pet-share/releases/latest) · [개인정보와 통신 설명](PRIVACY.md)

설치용 EXE는 제공하지 않습니다. Python 3.12 이상(tkinter 포함)이 필요하며, 설치 스크립트가 앱 전용 가상환경에 Pillow를 준비합니다. 관리자 권한은 필요하지 않습니다.

## 직접 설정

1. 최신 Release의 `claude-pet-X.Y.Z.zip`과 GitHub 자산 SHA-256을 확인합니다.
2. ZIP을 임시 폴더에 풀고 코드를 검토합니다.
3. `python -X utf8 -I install.py --package <ZIP 경로> --inspect`로 변경 범위를 확인합니다.
4. 같은 명령에서 `--inspect`를 빼고 실행합니다. 또는 저장소의 `setup.ps1 -Python <python.exe 경로>`가 최신 ZIP 확인·다운로드·체크섬 검사를 수행합니다.
5. 이후 설치 폴더의 `Start Pet.cmd` 또는 트레이 아이콘 더블클릭으로 켭니다.

설치 위치는 `%USERPROFILE%/.claude/claude-pet`입니다. 기존 설정을 백업하고 펫 훅만 병합하며, 로그인 시 트레이를 시작합니다. 개발용 Git 체크아웃은 자동으로 덮어쓰지 않습니다.

## 기능

- 펫 외형을 로봇, Charmander(파이리), Tokito Muichiro(무이치로) 중에서 선택.
- Claude Code·Chat·Cowork 상태를 펫과 대화별 말풍선으로 표시.
- 완료 알림은 확인할 때까지 유지. 말풍선에서 대화 열기·메시지 보내기.
- 다중 모니터, 위치 기억, 대화별 크기·폰트·투명도와 로컬 OCR 자동 투명화.
- 주황색 픽셀 트레이, 펫 숨기기·다시 켜기.
- 자동 실행 설정에서 Windows 로그인 시 / Claude 실행 시를 선택.
- 트레이 → Claude 펫 삭제로 전용 파일과 연동을 제거.

## 업데이트

시작 후 및 5분마다 정식 Release를 확인합니다. 트레이·펫 메뉴의 **업데이트**에서 새 버전을 확인하고 적용할 수 있습니다. 기본은 알림/수동 적용이며, **자동 업데이트**를 켜면 다운로드 후 입력·드래그·메뉴 조작이 끝나기를 기다렸다 적용합니다. 작업 중인 Claude 대화 자체는 중단하지 않습니다.

프로그램 소스만 교체하고 개인 설정은 보존합니다. 다운로드·파일 체크섬이 다르면 적용하지 않으며, 새 펫이 실행 검사를 통과하지 못하면 이전 코드를 복구합니다. GitHub에 개발 코드를 올리는 것만으로 배포되지 않고 **새 정식 Release**를 만들 때 전달됩니다.

## 한계

Windows 10/11 전용입니다. Claude 앱의 접근성 이름과 로컬 파일 형식이 달라지면 일부 연동을 수정해야 할 수 있습니다. 일반 Chat은 대화별 정보가 제한되어 말풍선 하나로 표시됩니다. 기관 PC의 다운로드·실행 정책을 우회하지 않습니다.

## Third-party font attribution

The small bitmap lettering used on the Mung Morning nameplate was rasterized from Galmuri11 by Lee Minseo (quiple). Copyright (c) 2019–2025 Lee Minseo. It is distributed under the SIL Open Font License, Version 1.1. The complete license text follows; the original font files are not included in the update package.

```text
Copyright (c) 2019–2025 Lee Minseo (quiple@quiple.dev)

This font software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
https://openfontlicense.org


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```
