from docutils import nodes

# create a node tree
paragraph = nodes.paragraph(text='Hello, world!')
emphasis = nodes.emphasis(text='world')
paragraph += emphasis

# replace the emphasis node with a new strong node
strong = nodes.strong(text='Python')

emphasis.replace_self(strong)

# print the modified node tree
print(paragraph.pformat())
