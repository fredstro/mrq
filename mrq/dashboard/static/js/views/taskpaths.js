define(["jquery", "underscore", "views/generic/datatablepage", "models"],function($, _, DataTablePage, Models) {

  return DataTablePage.extend({

    el: '.js-page-taskpaths',

    template:"#tpl-page-taskpaths",

    events:{
    },

    renderDatatable:function() {

      var self = this;

      var datatableConfig = self.getCommonDatatableConfig("taskpaths");

      _.extend(datatableConfig, {
        "aoColumns": [

          {
            "sTitle": "Name",
            "sClass": "col-name",
            "sType": "string",
            "mData":function(source, type, val) {
              return "<a href='/#jobs?path="+source._id+"'>"+source._id+"</a>";
            }
          },
          {
            "sTitle": "Jobs",
            "sClass": "col-jobs",
            "sType":"numeric",
            "mData":function(source, type, val) {
              var cnt = source.jobs || 0;

              if (type == "display") {
                return "<a href='/#jobs?path="+source._id+"'>"+cnt+"</a>"
                 + "<br/>"
                 + '<span class="inlinesparkline" values="'+self.addToCounter("taskpath."+source._id, cnt, 50).join(",")+'"></span>';
              } else {
                return cnt;
              }
            },
            "fnCreatedCell": function (nTd, sData, oData, iRow, iCol) {
              setTimeout(function() {
                $(".inlinesparkline", nTd).sparkline("html", {"width": "100px", "height": "30px", "defaultPixelsPerValue": 1});
              }, 10);
            }
          }

        ],
        "aaSorting":[ [0,'asc'] ],
      });

      this.initDataTable(datatableConfig);

    }
  });

});
