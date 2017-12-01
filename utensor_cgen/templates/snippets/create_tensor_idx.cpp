{% if create_sptr %}
S_TENSOR {{sptr_name}};
{% endif %}
{
    TensorIdxImporter t_import;
    {{ctx_var_name}}.add(t_import.{{dtype}}_import("{{data_dir}}/{{idx_fname}}", "{{tensor_name}}"), {{init_count}});
    {% if create_sptr %}
    {{sptr_name}} = {{ctx_var_name}}.get("{{tensor_name}}");
    {% endif %}
}