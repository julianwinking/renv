# Ideation for a paper

## Problem
Currently more people in research are trying to use large language models (LLMs) to help with their research. One big limitation of LLMs is that they can hallucinate. This shows in the form of generating false information, or making up references. The ladder one can be addressed by introducing checks of references in the sources of a paper if they referene the correct paper name and if it already exists. This is partially already done on plattforms like Google scholar but could also be moved into the latex code of the paper itself by directly referencing a paper publication link. Still that would leave the problem that an LLM might not have to read through a paper when referencing it or only read the abstract. (happned to me personally, check if that is a known proble.). What we can see already in tools like Anara.com is an idexing of a pdf in chunks and then referencing exact chunks when retrieving information. 

## Solution
Generally, there is a lot inbetween the lines of a paper that is not explicitly written down but a human researcher knows during the writing process. A frist step could be to add a reasoning line in-between paper sentences to make the implicit knowledge explicit. This would be a first step to make the paper more transparent and easier to check for correctness and AI iterations to not lose on context from what is maybe in notes and what is written down in the actual paper. This could happen on a section basis, a paragraph basis and a sentence basis.

Further, I would like to explore to extend that to references. Currently, in technical fields you would only cite a reference at the end of a sentecence. I think it would be actual helpful to list the exact place from the original paper (line number or the chunked vector when we assume all papers could be indexed in a standardized way as anara currently does it but also a local paper indexing in the personal storage could already work)

## Approach
- Implement local vector indexing approach
- Write my own paper suggesting this approach using the other papers I have read as references and explicitly referencing the exact place in the paper where I got the information from including the hidden text intructions that improve the reasoning of the paper and make it more transparent.
- Show that this approach enables it to create reasoning chains of multiple papers (that were building on each other) and visualize those to see how the reasoning is built on top of each other and how the references are connected to each other.
- Show that this approach can be used to check for hallucinations in the references and also to check for the correctness of the paper itself by checking if the reasoning lines are correct and if the references
  - This could also be a standadrdized approach that is then applied in reviewing papers because it makes it more transparent where a paper is coming from and what the actual additions are.