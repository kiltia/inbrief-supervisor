def get_references(stories_nums, references):
    references_on_stories = []
    for nums in stories_nums:
        references_on_stories.append([references[i] for i in nums])
    return references_on_stories
