# Lex V2 bot: PhotoSearchBot

Locale: English (US). Intent: SearchIntent. Two optional slots, both of slot type PhotoLabel.

## Slot type: PhotoLabel
Slot value resolution: **Expand values** (so labels that are not in the list, like custom labels "Sam", still fill the slot).
Seed values (add more if you like):
dog, cat, bird, tree, person, car, beach, flower, mountain, sky, water, building, food, people, child, animal, plant, grass, ocean, city, bicycle, horse, sunset, snow, house, table, chair, laptop, phone, book, park, ball, boat, bridge, road, cloud, sam, sally

## Slots
| Name | Slot type | Required |
|---|---|---|
| keywordOne | PhotoLabel | No (optional) |
| keywordTwo | PhotoLabel | No (optional) |

## Sample utterances
{keywordOne}
{keywordOne} {keywordTwo}
{keywordOne} and {keywordTwo}
show me {keywordOne}
show me {keywordOne} and {keywordTwo}
show me {keywordOne} photos
show me photos of {keywordOne}
show me photos with {keywordOne}
show me photos with {keywordOne} in them
show me photos with {keywordOne} and {keywordTwo}
show me photos with {keywordOne} and {keywordTwo} in them
show me pictures of {keywordOne}
show me pictures of {keywordOne} and {keywordTwo}
show me images of {keywordOne}
photos of {keywordOne}
photos of {keywordOne} and {keywordTwo}
pictures with {keywordOne} and {keywordTwo}
images with {keywordOne}
find {keywordOne}
find photos of {keywordOne}
find {keywordOne} and {keywordTwo}
search for {keywordOne}
search for {keywordOne} and {keywordTwo}
I want to see {keywordOne}
I want to see {keywordOne} and {keywordTwo}
can you show me {keywordOne}
do I have photos of {keywordOne}
get me {keywordOne} pictures
