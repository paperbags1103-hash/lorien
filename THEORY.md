# 그래프와 온톨로지 이론 — 온톨로지 메모리 구현을 위한 가이드

> 이 문서는 AI 에이전트용 온톨로지 메모리 시스템을 만들기 위해 알아야 할 이론을 정리한 것입니다.
> 학문적 깊이보다는 "구현에 필요한 수준"에 맞추었습니다.

---

## 1부: 그래프 이론

### 1.1 그래프란 무엇인가

그래프는 **"것(thing)"과 "관계(relation)"**의 집합입니다.

수학적으로는 G = (V, E)라고 씁니다.
- **V (Vertex, 정점)**: 노드라고도 부릅니다. 하나의 개체를 나타냅니다.
- **E (Edge, 간선)**: 두 노드 사이의 연결을 나타냅니다.

일상에서 가장 쉬운 예는 **지하철 노선도**입니다.
- 역 = 노드
- 역 사이의 연결 = 엣지

```
[서울역] ----1호선---- [시청역] ----2호선---- [을지로입구]
```

### 1.2 그래프의 종류

구현할 때 알아야 할 그래프 종류는 세 가지입니다.

#### 무방향 그래프 (Undirected Graph)
엣지에 방향이 없습니다. "A와 B는 친구"처럼 양쪽이 대등한 관계입니다.

```
[철수] ---- 친구 ---- [영희]
```
철수가 영희의 친구이면, 영희도 철수의 친구입니다.

#### 방향 그래프 (Directed Graph)
엣지에 방향이 있습니다. 온톨로지 메모리에서 주로 사용하는 형태입니다.

```
[철수] ---좋아함--→ [영희]
```
철수가 영희를 좋아한다고 해서, 영희가 철수를 좋아하는 건 아닙니다.

#### 속성 그래프 (Property Graph)
노드와 엣지에 추가 정보(속성)를 붙일 수 있는 그래프입니다.
**온톨로지 메모리에서 가장 핵심적인 형태**입니다.

```
[철수]                    ---좋아함---→         [영희]
 ├ 이름: "김철수"           ├ 시작: 2024-03        ├ 이름: "이영희"
 ├ 나이: 28                └ 강도: "매우"          └ 나이: 26
 └ 직업: "개발자"
```

노드에도 속성이 있고, 엣지에도 속성이 있습니다.
이렇게 하면 "언제부터 좋아했는지", "얼마나 좋아하는지" 같은 정보까지 표현할 수 있습니다.

### 1.3 그래프 탐색

저장한 지식을 활용하려면 그래프를 탐색(traversal)해야 합니다.
온톨로지 메모리에서 쓰는 핵심 탐색 방법은 두 가지입니다.

#### 이웃 탐색 (Neighbor Lookup)
특정 노드에 직접 연결된 노드를 찾는 것입니다. 가장 기본적이고 자주 씁니다.

```
질문: "철수와 관련된 것들은?"

[Python] ←--사용-- [철수] ---근무--→ [A회사]
                     |
                     └---취미--→ [러닝]

결과: Python, A회사, 러닝
```

#### 경로 탐색 (Path Traversal)
여러 엣지를 따라가면서 간접적으로 연결된 노드를 찾는 것입니다.
온톨로지 메모리에서 **추론**의 기반이 됩니다.

```
질문: "React를 업그레이드하면 뭐가 영향받지?"

[React] ←--의존-- [react-grid-layout] ---사용처--→ [대시보드]
                                                       |
                                                       └---담당자--→ [박OO]

경로: React → react-grid-layout → 대시보드 → 박OO
결과: "React를 바꾸면 react-grid-layout에 영향, 
       그러면 대시보드가 영향받고, 담당자 박OO에게 알려야 함"
```

2단계, 3단계를 넘어서 탐색할수록 더 깊은 추론이 가능하지만,
너무 멀리 가면 관련 없는 결과가 나올 수 있어서 보통 2~3단계까지만 탐색합니다.

### 1.4 그래프 질의 언어

그래프 DB에서 데이터를 조회하려면 질의 언어를 사용합니다.
가장 널리 쓰이는 것이 **Cypher**입니다. Kuzu도 Cypher를 지원합니다.

Cypher의 핵심 문법:

```cypher
// 노드는 ()로 표현
(n:Person)          -- Person 타입의 노드 n

// 관계는 []와 화살표로 표현
-[:WORKS_AT]->      -- WORKS_AT 관계 (방향 있음)

// 패턴 매칭: "Person이 Company에 근무하는" 패턴을 찾아라
MATCH (p:Person)-[:WORKS_AT]->(c:Company)
RETURN p.name, c.name

// 조건 추가
MATCH (p:Person)-[:WORKS_AT]->(c:Company)
WHERE c.name = "A회사"
RETURN p.name

// 여러 단계 탐색
MATCH (p:Person)-[:WORKS_AT]->(c:Company)-[:LOCATED_IN]->(city:City)
RETURN p.name, city.name
// → "사람이 다니는 회사가 위치한 도시"를 한 번에 조회
```

SQL이 표(테이블)에서 데이터를 꺼내는 언어라면,
Cypher는 그래프에서 패턴을 찾아내는 언어입니다.

---

## 2부: 온톨로지 이론

### 2.1 온톨로지란 무엇인가

온톨로지(Ontology)는 원래 철학 용어로 "존재론"이라는 뜻입니다.
컴퓨터 과학에서는 **"특정 영역의 지식을 체계적으로 표현하는 방법"**을 말합니다.

쉽게 말하면, 온톨로지는 **"세상을 어떤 틀로 이해할 것인가"에 대한 설계도**입니다.

예를 들어, "음식"에 대한 온톨로지를 만든다면:

```
[음식] 이라는 개념 아래에
  ├── [한식] ── [중식] ── [양식]    ← 분류 체계
  │
  ├── 음식에는 [재료]가 있다        ← 관계 정의
  ├── 음식에는 [조리법]이 있다
  ├── 음식에는 [영양소]가 있다
  │
  └── [김치찌개]는 [한식]의 일종     ← 구체적 사례
      ├── 재료: 김치, 돼지고기, 두부
      └── 조리법: 끓이기
```

단순히 "김치찌개는 한식이다"라는 사실을 저장하는 게 아니라,
**"음식이라는 세계에는 어떤 종류의 것들이 있고, 그것들이 어떻게 연결되는가"**를
정의하는 것이 온톨로지입니다.

### 2.2 온톨로지의 구성 요소

온톨로지는 다섯 가지 요소로 이루어집니다.

#### 클래스 (Class)
개념의 종류입니다. "이런 종류의 것이 존재한다"를 정의합니다.

```
Person (사람)
Organization (조직)
Location (장소)
Event (사건)
Concept (추상 개념)
```

#### 인스턴스 (Instance)
클래스의 구체적인 예입니다.

```
클래스 Person의 인스턴스: 김철수, 이영희, 박민수
클래스 Location의 인스턴스: 서울, 판교, 강남역
```

#### 속성 (Property / Attribute)
인스턴스가 가지는 고유한 값입니다.

```
김철수
  ├── 이름: "김철수"
  ├── 나이: 28
  ├── 이메일: "cs@example.com"
  └── 직업: "프론트엔드 개발자"
```

#### 관계 (Relation)
두 인스턴스 사이의 연결입니다. 온톨로지에서 가장 중요한 부분입니다.

```
김철수 --근무처-→ A회사
김철수 --거주지-→ 서울
A회사  --위치-→ 판교
김철수 --동료-→ 이영희
```

#### 제약 조건 (Constraint / Axiom)
"이런 관계는 성립할 수 없다" 같은 규칙입니다.

```
- 한 사람은 두 곳에 동시에 거주할 수 없다 (단, 이중 거주는 예외)
- 태어난 날짜는 오늘보다 미래일 수 없다
- "의존" 관계는 순환할 수 없다 (A→B→C→A 불가)
```

### 2.3 클래스 계층 구조 (Taxonomy)

온톨로지의 큰 힘 중 하나는 **계층 구조를 통한 상속**입니다.

```
Thing (최상위)
  ├── Entity (실체)
  │     ├── Person (사람)
  │     │     ├── Developer (개발자)
  │     │     └── Designer (디자이너)
  │     ├── Organization (조직)
  │     │     ├── Company (회사)
  │     │     └── School (학교)
  │     └── Place (장소)
  │           ├── City (도시)
  │           └── Building (건물)
  ├── Event (사건)
  │     ├── Meeting (회의)
  │     └── Decision (결정)
  └── AbstractConcept (추상 개념)
        ├── Skill (기술)
        ├── Rule (규칙)
        └── Goal (목표)
```

계층 구조의 장점은 **상속**입니다.
"Person은 이름과 나이를 가진다"라고 정의하면,
Developer와 Designer도 자동으로 이름과 나이를 가집니다.

"Developer는 프로그래밍 언어를 사용한다"라고 추가하면,
Developer에만 적용되고 Designer에는 적용되지 않습니다.

### 2.4 관계의 종류

온톨로지에서 관계는 단순히 "연결"이 아니라, **의미를 가진 연결**입니다.
구현할 때 자주 쓰는 관계 유형들을 정리합니다.

#### IS-A (상위-하위 관계)
"A는 B의 일종이다"

```
[Python] --IS_A-→ [프로그래밍 언어]
[개발자] --IS_A-→ [사람]
```

이 관계가 있으면 "프로그래밍 언어의 특징"을 Python에도 적용할 수 있습니다.

#### HAS-A (포함 관계)
"A는 B를 가지고 있다"

```
[프로젝트] --HAS-→ [팀원]
[프로젝트] --HAS-→ [마감일]
[컴퓨터]   --HAS-→ [CPU]
```

#### PART-OF (부분 관계)
"A는 B의 일부이다" (HAS-A의 반대 방향)

```
[마케팅팀] --PART_OF-→ [A회사]
[2장]      --PART_OF-→ [보고서]
```

#### CAUSES (인과 관계)
"A가 B를 일으킨다"

```
[야근 증가] --CAUSES-→ [피로 누적]
[피로 누적] --CAUSES-→ [업무 효율 저하]
```

온톨로지 메모리에서 **추론의 핵심**입니다.
인과 관계를 따라가면 "왜 그런지", "앞으로 어떻게 될지" 예측할 수 있습니다.

#### DEPENDS-ON (의존 관계)
"A는 B에 의존한다"

```
[react-grid-layout] --DEPENDS_ON-→ [React 18]
[배포]               --DEPENDS_ON-→ [테스트 통과]
```

#### TEMPORAL (시간 관계)
"A 다음에 B가 발생했다"

```
[입사] --BEFORE-→ [첫 프로젝트] --BEFORE-→ [승진]
```

#### CONTRADICTS (모순 관계)
"A와 B는 서로 충돌한다"

```
[React 19 사용 목표] --CONTRADICTS-→ [react-grid-layout 1.4.4 고정 규칙]
```

온톨로지 메모리에서 **모순 감지**의 기반입니다.

### 2.5 온톨로지 vs 다른 지식 표현 방식

왜 온톨로지를 써야 하는지, 다른 방식과 비교하면 더 명확해집니다.

#### 키-값 저장소 (Key-Value)
```
user_name: "김철수"
user_job: "개발자"
user_hobby: "러닝"
```
단순하지만, "개발자와 러닝 사이에 관계가 있는가?" 같은 질문에 답할 수 없습니다.
정보가 서로 분리되어 있어서 연결이 불가능합니다.

#### 관계형 데이터베이스 (RDB, 테이블)
```
사람 테이블: | 이름 | 직업 | 취미 |
             | 철수 | 개발자 | 러닝 |

회사 테이블: | 이름 | 위치 |
             | A사  | 판교 |
```
테이블 간에 JOIN으로 연결할 수 있지만,
관계의 종류가 미리 정해져 있어야 합니다 (스키마가 고정적).
새로운 종류의 관계를 추가하려면 테이블 구조를 바꿔야 합니다.

#### 온톨로지 (그래프)
```
[철수] --직업-→ [개발자] --필요기술-→ [Python]
  |                                      |
  └--취미-→ [러닝] --효과-→ [체력]     [Python] --용도-→ [데이터 분석]
```
관계를 자유롭게 추가할 수 있고,
여러 단계를 넘나들며 탐색할 수 있습니다.
"철수의 직업에 필요한 기술의 용도는?" 같은 복잡한 질문에도 답할 수 있습니다.

---

## 3부: 온톨로지 메모리를 위한 핵심 개념

여기서부터는 일반 이론을 넘어서, **AI 에이전트의 온톨로지 메모리**에 특화된 개념들입니다.

### 3.1 트리플 (Triple)

온톨로지의 모든 지식은 **트리플(triple)** 형태로 표현할 수 있습니다.

```
(주어, 술어, 목적어)
(Subject, Predicate, Object)
```

예시:
```
(김철수, 근무처, A회사)
(A회사, 위치, 판교)
(김철수, 사용언어, Python)
(Python, 유형, 프로그래밍 언어)
```

모든 자연어 문장을 트리플로 분해할 수 있다는 것이 핵심입니다.

"김철수는 판교에 있는 A회사에서 Python으로 개발한다"
→ (김철수, 근무처, A회사)
→ (A회사, 위치, 판교)
→ (김철수, 사용언어, Python)
→ (김철수, 직업, 개발자)

LLM에게 "이 문장을 트리플로 분해해줘"라고 요청하면,
자연어를 온톨로지로 변환하는 첫 단계가 완성됩니다.

### 3.2 개체 해소 (Entity Resolution)

같은 것을 다르게 부르는 문제입니다. 온톨로지 메모리에서 반드시 해결해야 합니다.

```
"React", "리액트", "React.js", "ReactJS"  → 전부 같은 것
"이 회사", "우리 회사", "A회사"             → 문맥에 따라 같은 것
"그 사람", "팀장님", "박OO"                → 같은 사람일 수 있음
```

해결 방법:
1. **정규화(Normalization)**: 모든 이름을 하나의 표준 형태로 통일
   - "React.js" → "React", "리액트" → "React"
2. **별칭(Alias) 저장**: 하나의 노드에 여러 이름을 연결
   - [React] --별칭→ ["리액트", "React.js", "ReactJS"]
3. **LLM 활용**: 문맥을 보고 "이 회사"가 어떤 회사인지 판단

### 3.3 시간축 (Temporal Dimension)

온톨로지 메모리가 단순 지식 그래프와 다른 가장 큰 차이점입니다.
사람의 상황은 시간에 따라 변합니다.

```
2024년 3월: (철수, 근무처, A회사)
2024년 9월: (철수, 근무처, B회사)    ← A회사에서 이직

2024년 1월: (철수, 목표, 프리랜서)
2024년 6월: (철수, 목표, 대기업)     ← 목표가 바뀜
```

구현 방법: 모든 트리플에 **유효 기간(valid_from, valid_to)**을 추가합니다.

```
(철수, 근무처, A회사, valid_from=2022-01, valid_to=2024-08)
(철수, 근무처, B회사, valid_from=2024-09, valid_to=현재)
```

이렇게 하면:
- "철수는 지금 어디서 일해?" → B회사 (현재 유효한 관계)
- "철수는 어디서 일했었어?" → A회사 (과거 관계)
- "철수의 직장이 바뀌었네?" → A회사에서 B회사로 변경 감지

### 3.4 신뢰도 (Confidence)

온톨로지 메모리에 저장되는 정보가 모두 확실한 건 아닙니다.

```
(철수, 직업, 개발자, 신뢰도=1.0)      ← 직접 말한 사실
(철수, 관심분야, AI, 신뢰도=0.8)      ← 대화에서 자주 언급
(철수, 이직의향, 있음, 신뢰도=0.4)    ← 한 번 언급, 농담일 수도
```

신뢰도를 관리하면:
- 확실한 정보와 추측을 구분할 수 있습니다
- 여러 번 확인된 정보는 신뢰도가 올라갑니다
- 오래되어 확인이 안 된 정보는 신뢰도가 내려갑니다

### 3.5 추론 (Inference)

저장된 관계를 바탕으로 **명시적으로 저장하지 않은 새로운 사실을 도출**하는 것입니다.
온톨로지 메모리의 가장 강력한 기능입니다.

#### 이행적 추론 (Transitive Inference)
```
저장된 사실:
  (철수, 근무처, A회사)
  (A회사, 위치, 판교)
  (판교, 소속, 경기도)

추론 가능:
  → 철수는 경기도에서 일한다 (직접 저장하지 않았지만 도출 가능)
```

#### 역방향 추론 (Inverse Inference)
```
저장된 사실:
  (철수, 상사, 박팀장)

추론 가능:
  → 박팀장의 부하직원에 철수가 포함됨
```

#### 상속 추론 (Inheritance Inference)
```
저장된 사실:
  (개발자, IS_A, 사람)
  (사람, HAS, 이름)
  (철수, IS_A, 개발자)

추론 가능:
  → 철수는 이름을 가진다 (사람의 속성을 상속)
```

#### 인과 추론 (Causal Inference)
```
저장된 사실:
  (야근 증가, CAUSES, 수면 부족)
  (수면 부족, CAUSES, 집중력 저하)
  (집중력 저하, CAUSES, 업무 효율 감소)

추론 가능:
  → 야근 증가는 궁극적으로 업무 효율 감소를 일으킨다
  → (역으로) 업무 효율을 높이려면 야근을 줄여야 할 수 있다
```

### 3.6 모순 감지 (Contradiction Detection)

온톨로지의 구조를 활용하면 정보 간의 모순을 자동으로 발견할 수 있습니다.

#### 직접 모순
```
(철수, 거주지, 서울, 시점=현재)
(철수, 거주지, 부산, 시점=현재)
→ 모순! 동시에 두 곳에 거주할 수 없음 (제약 조건 위반)
```

#### 추론을 통한 모순
```
(철수, 목표, React 19 도입)
(프로젝트, 규칙, react-grid-layout 1.4.4 고정)
(react-grid-layout 1.4.4, 미지원, React 19)
→ 모순! 목표를 달성하면 규칙을 어기게 됨
```

이런 모순 감지가 바로 graphmem이 하려는 일의 확장판입니다.
graphmem은 코드 규칙에 한정하지만, 범용 온톨로지 메모리는
삶의 모든 영역에서 모순을 감지할 수 있습니다.

---

## 4부: 구현을 위한 설계 패턴

### 4.1 스키마 설계 원칙

#### 원칙 1: 느슨하게 시작하라 (Start Loose)
처음부터 완벽한 스키마를 만들려 하지 마세요.
최소한의 클래스와 관계로 시작하고, 실제 데이터를 넣어보면서 확장하세요.

```
# 최소 시작 스키마
노드: Entity, Concept, Event
관계: RELATED_TO (일단 다 이걸로)

# 데이터를 넣다 보면 필요성이 보임
→ "아, RELATED_TO만으로는 부족하다. CAUSES가 따로 필요하다"
→ "Event에 시간 속성이 있어야 한다"
→ "Person과 Organization을 Entity에서 분리해야 한다"
```

#### 원칙 2: 관계 이름은 동사로 (Relations as Verbs)
관계 이름이 명확해야 나중에 추론할 때 의미가 살아납니다.

```
좋음: WORKS_AT, DEPENDS_ON, CAUSES, CREATED_BY
나쁨: REL_1, CONNECTION, LINK, ASSOCIATED
```

#### 원칙 3: 메타데이터를 항상 붙여라
모든 트리플에 최소한 이 세 가지는 붙이세요.

```
{
  subject: "철수",
  predicate: "근무처",
  object: "A회사",
  
  // 메타데이터
  created_at: "2024-03-15",     // 이 정보가 저장된 시점
  confidence: 0.95,              // 신뢰도
  source: "사용자 직접 입력"      // 정보의 출처
}
```

### 4.2 Kuzu에서의 구현 패턴

실제 Kuzu 코드로 어떻게 구현하는지 보여드립니다.

```python
import kuzu

# 데이터베이스 생성
db = kuzu.Database("./ontology_memory")
conn = kuzu.Connection(db)

# === 노드 테이블 (클래스) 정의 ===

conn.execute("""
CREATE NODE TABLE Entity(
    id STRING,
    name STRING,
    type STRING,          -- person, organization, place 등
    created_at TIMESTAMP,
    confidence DOUBLE,
    PRIMARY KEY(id)
)""")

conn.execute("""
CREATE NODE TABLE Concept(
    id STRING,
    name STRING,
    category STRING,      -- skill, goal, rule 등
    created_at TIMESTAMP,
    confidence DOUBLE,
    PRIMARY KEY(id)
)""")

conn.execute("""
CREATE NODE TABLE Event(
    id STRING,
    name STRING,
    occurred_at TIMESTAMP,
    created_at TIMESTAMP,
    confidence DOUBLE,
    PRIMARY KEY(id)
)""")

# === 관계 테이블 정의 ===

conn.execute("""
CREATE REL TABLE RELATED_TO(
    FROM Entity TO Entity,
    relation_type STRING,    -- works_at, lives_in, knows 등
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,
    confidence DOUBLE,
    source STRING
)""")

conn.execute("""
CREATE REL TABLE HAS_CONCEPT(
    FROM Entity TO Concept,
    relation_type STRING,    -- interested_in, skilled_at, goal 등
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,
    confidence DOUBLE,
    source STRING
)""")

conn.execute("""
CREATE REL TABLE CAUSES(
    FROM Event TO Event,
    confidence DOUBLE,
    source STRING
)""")
```

### 4.3 자연어 → 트리플 변환 패턴

LLM에게 보내는 프롬프트의 기본 구조입니다.

```python
prompt = """
다음 문장에서 지식 트리플을 추출해주세요.

규칙:
1. 각 트리플은 (주어, 관계, 목적어) 형태입니다.
2. 주어와 목적어는 명사(구)여야 합니다.
3. 관계는 구체적인 동사여야 합니다.
4. 같은 대상은 같은 이름으로 통일하세요.
5. 확실하지 않은 정보에는 confidence를 낮게 설정하세요.

문장: "김철수는 판교에 있는 A회사에서 3년째 프론트엔드 개발을 하고 있으며, 
       최근 AI에 관심을 갖기 시작했다."

JSON으로만 응답하세요:
{
  "triples": [
    {
      "subject": "...",
      "predicate": "...", 
      "object": "...",
      "confidence": 0.0~1.0
    }
  ]
}
"""

# 예상 출력:
# {
#   "triples": [
#     {"subject": "김철수", "predicate": "works_at", "object": "A회사", "confidence": 0.95},
#     {"subject": "A회사", "predicate": "located_in", "object": "판교", "confidence": 0.95},
#     {"subject": "김철수", "predicate": "role", "object": "프론트엔드 개발자", "confidence": 0.90},
#     {"subject": "김철수", "predicate": "tenure_years", "object": "3", "confidence": 0.85},
#     {"subject": "김철수", "predicate": "interested_in", "object": "AI", "confidence": 0.70}
#   ]
# }
```

### 4.4 추론 구현 패턴

Cypher 질의를 활용한 추론 예시입니다.

```cypher
// 1. 이행적 추론: "철수가 일하는 곳의 도시는?"
MATCH (p:Entity)-[:RELATED_TO {relation_type: 'works_at'}]->(c:Entity)
      -[:RELATED_TO {relation_type: 'located_in'}]->(city:Entity)
WHERE p.name = '김철수'
RETURN city.name

// 2. 영향 범위 추론: "React를 바꾸면 뭐가 영향받지?"
// (최대 3단계까지 탐색)
MATCH path = (start:Concept)-[:HAS_CONCEPT|RELATED_TO*1..3]-(affected)
WHERE start.name = 'React'
RETURN affected.name, length(path) as distance

// 3. 모순 감지: "현재 시점에서 모순되는 관계 찾기"
MATCH (a:Entity)-[r1:RELATED_TO]->(target),
      (a)-[r2:RELATED_TO]->(target2)
WHERE r1.relation_type = r2.relation_type
  AND target <> target2
  AND r1.valid_to IS NULL    -- 현재 유효
  AND r2.valid_to IS NULL    -- 현재 유효
RETURN a.name, r1.relation_type, target.name, target2.name
```

---

## 5부: 참고 자료

### 학습 순서 추천

1. **그래프 기초**: NetworkX 튜토리얼 (Python으로 그래프를 직접 만들어보기)
2. **Cypher 언어**: Neo4j Cypher 튜토리얼 (무료 온라인, Kuzu에도 적용 가능)
3. **온톨로지 실습**: Protégé (온톨로지 편집 도구, 시각적으로 구조를 설계할 수 있음)
4. **Kuzu 문서**: https://docs.kuzudb.com (실제 구현에 사용할 DB)
5. **GraphRAG 논문**: Microsoft의 GraphRAG 논문 (LLM + 그래프의 결합 사례)

### 핵심 용어 정리

| 한국어 | 영어 | 설명 |
|--------|------|------|
| 노드 | Node / Vertex | 그래프의 점. 하나의 개체를 나타냄 |
| 엣지 | Edge | 그래프의 선. 두 노드 사이의 관계 |
| 트리플 | Triple | (주어, 관계, 목적어) 형태의 지식 단위 |
| 클래스 | Class | 노드의 종류/분류 |
| 인스턴스 | Instance | 클래스의 구체적 예 |
| 속성 | Property | 노드나 엣지에 붙는 추가 정보 |
| 온톨로지 | Ontology | 지식의 체계적 표현 구조 |
| 탐색 | Traversal | 그래프에서 노드를 따라가며 정보를 찾는 것 |
| 추론 | Inference | 저장된 관계로부터 새로운 사실을 도출하는 것 |
| 개체 해소 | Entity Resolution | 같은 대상의 다른 표현을 통일하는 것 |
| 스키마 | Schema | 데이터 구조의 설계도 |
| 사이퍼 | Cypher | 그래프 DB 질의 언어 |

---

*이 문서는 온톨로지 메모리 시스템 구현 프로젝트를 위해 작성되었습니다.*
*이론을 읽은 후에는 반드시 작은 예제를 직접 코드로 구현해보세요.*
