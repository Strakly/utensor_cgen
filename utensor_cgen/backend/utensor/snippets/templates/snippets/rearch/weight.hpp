const {{ dtype }} {{ var_name }} [{{ size }}] = { {%for elem in data%} {{elem}}, {%endfor%} };