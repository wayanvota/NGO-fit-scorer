# Defining your Strategy Profile

Read this before you score anything. The engine in this template is generic on
purpose, but a generic scorer is worthless. The tool is only as good as the
profile you give it, and a vague profile produces confident, mushy scores that
are worse than no tool at all, because they carry an air of objectivity they
have not earned.

This guide explains why the profile matters and how to make yours sharp.

## Why a sharp profile matters

A funding-fit scorer answers one question: does this opportunity fit *our*
strategy well enough to spend staff time on. That question only has meaning if
"our strategy" is stated precisely. If your profile says you fund "health and
education in underserved communities," almost everything scores medium-high,
the tool never says a hard no, and it saves you nothing. The value of the tool
is in the opportunities it tells you to *skip*, and it can only do that if it
knows what you are not.

The organizations that get value from this tool are the ones whose profile is
opinionated to the point of being uncomfortable. It names the two or three
countries that matter and treats the rest as a penalty. It says out loud that
unrestricted money is worth more than restricted money, and by how much. It
encodes the eligibility rules and values lines it will not cross. A profile that
could belong to any nonprofit belongs to none.

## The failure mode to avoid

The temptation when you fill this in is to keep every option open: broad
dimensions, even weights, few hard filters, generous language. Resist it. Even
weights mean nothing is prioritized. Broad dimensions mean every opportunity is
"kind of a fit." The result is a tool that always says maybe. If you catch
yourself writing a dimension description that would be true of any funder, stop
and make it specific to your organization or delete it.

## The four things you define

### 1. The mission and context (profile_doc)

A few sentences that ground every score: your mission, who you serve, your
current priorities and geographies, your funding preferences, and any values
lines you will not cross. The scorer reads this on every run. Be concrete.
"Maternal health via telemedicine in rural India and Kyrgyzstan, moving toward
government-financed national scale" is useful. "Improving lives through
technology" is not.

### 2. The scoring dimensions and weights

Dimensions are the axes you judge fit on. Each has a label, a one-line
description the scorer uses as its rubric, and an integer weight. Weights must
sum to 100, and that constraint is the point: it forces you to say what matters
most. If mission fit and funder relationship have the same weight, you are
saying a warm funder for off-mission work is as good as a cold funder for
on-mission work. Most organizations do not believe that. Make the weights argue.

Five to eight dimensions is the right range. Fewer and the score is blunt; more
and the weights get so thin that nothing moves the total. Write each description
as the specific test you want applied, not a category name. "Does the work serve
women and families where there is no doctor" beats "Mission."

### 3. Hard filters, and the hard-versus-soft distinction

Hard filters are knockouts: conditions that should override the weighted score.
This template gives you two modes, and choosing correctly is what keeps the tool
honest.

A **hard** filter zeroes the score and marks the opportunity Disqualified. Use
it only for genuinely binary, unresolvable conditions: the work is outside your
mission, the terms violate a value you will not compromise, the funder requires
operating somewhere you will not go.

A **soft** filter caps the tier at Watch and flags the blocker, but keeps the
honest score. Use it for real but *resolvable* barriers. Organization-type
eligibility is the classic case: an RFP restricted to universities or registered
startups looks disqualifying, but a partnership, co-applicant, or fiscal-sponsor
arrangement often resolves it. A hard zero there hides opportunities you could
actually win through a partner. The template ships `ineligible_org_type` as soft
for exactly this reason. If you make everything hard, the tool will bury
winnable opportunities under false knockouts.

The test: if a smart development lead could plausibly get around the barrier with
a phone call or a partnership, it is soft. If nothing short of changing your
organization would fix it, it is hard.

### 4. Thresholds and tiers

Thresholds hold your money rules: the grant floor below which an opportunity is
weak on the funding dimension, the strategic tier above which it is a major
opportunity, how hard to penalize restricted funding, and whether a small
fully-restricted grant is an automatic knockout. Set the floor and strategic
tier to real numbers from your budget, not round guesses. Tiers are the score
cutoffs for Pursue, Pursue-with-review, Watch, and Pass; the defaults (80, 60,
40) are reasonable, but move them if your team's sense of "worth pursuing"
differs.

## How to build yours

Use the Setup screen. Paste your actual strategic plan or a rich description and
let the bootstrap agent draft a full profile, then edit every part of it. The
draft is a starting point, not an answer. The editing is where your judgment
enters, and it is not optional. Read the drafted weights and ask, for each one,
"would I defend this number in a room with my board." Where the answer is no,
change it.

Then let it learn. As your team logs corrections and real win and loss outcomes,
the recalibration agent proposes weight changes backed by evidence, which an
admin approves or rejects. The profile you write today is version one, not the
final word. But it has to be sharp to start, because the tool cannot learn its
way out of a profile that never had a point of view.
